import argparse
import sys
import os
import tempfile
import subprocess
import shlex
import pathlib
import configparser
import uuid as u


REPO_CONFIG_FILENAME = "slig.ini"


class GitError(RuntimeError):
    def __init__(self, returncode, stderr):
        RuntimeError.__init__(self, "Git process exited with code {}".format(returncode))
        self.stderr = stderr


class ClonedGitRepo:
    def __init__(self, remote, git_options):
        "Clone remote repo into a temp directory"

        self._git_options = git_options

        parent_dir = tempfile.mkdtemp()
        clone_result = subprocess.run(["git"] + git_options + ["clone", remote], cwd=parent_dir, capture_output=True)
        decoded_stderr = clone_result.stderr.decode(sys.stderr.encoding)
        print(decoded_stderr, file=sys.stderr)  # write stderr of git to stderr
        if clone_result.returncode == 0:
            # find cloned repository in parent_dir
            subdirs = list(pathlib.Path(parent_dir).iterdir())
            if len(subdirs) == 1:
                self.name = subdirs[0].name
                self.path = pathlib.Path(parent_dir) / self.name
            else:
                print("Error finding cloned repository in {}".format(parent_dir), file=sys.stderr)
                sys.exit(1)
        else:
            print("Git process exited with code {}".format(clone_result.returncode), file=sys.stderr)
            sys.exit(1)

    def _call_git_command(self, commands):
        result = subprocess.run(["git"] + self._git_options + commands, cwd=self.path, capture_output=True)
        decoded_stderr = result.stderr.decode(sys.stderr.encoding)
        print(decoded_stderr, file=sys.stderr)  # write stderr of git to stderr
        return (result.returncode, decoded_stderr)

    def _call_git_command_raise(self, commands):
        (returncode, decoded_stderr) = self._call_git_command(commands)
        if returncode != 0:
            raise GitError(returncode, decoded_stderr)

    def _sync_check_conflict(self):
        # push -> pull --rebase -> push
        # the first push is for speedup

        MAX_RETRY = 3

        ret_code, _ = self._call_git_command(["push"])
        if ret_code == 0:
            # push successful
            return True
        else:
            retry_cnt = 0
            while retry_cnt < MAX_RETRY:
                retry_cnt += 1
                try:
                    self._call_git_command_raise(["pull", "--rebase"])
                except GitError:
                    # pull conflict: lock acquired by others
                    return False

                try:
                    self._call_git_command_raise(["push"])
                    return True
                except GitError:
                    return False

            return False

    def initialize(self):
        "Create slig.in and push it into remote repository"

        # TODO: check if already initialized (REPO_CONFIG_FILENAME already exists)

        config = configparser.ConfigParser()
        config['locks'] = {}
        config['metadata'] = {"version": "1.0"}

        try:
            with open(self.path / REPO_CONFIG_FILENAME, "w") as file:
                config.write(file)

            self._call_git_command_raise(["add", REPO_CONFIG_FILENAME])
            self._call_git_command_raise(["commit", "-m", "initialize slig repository"])
            self._call_git_command_raise(["push"])
        except GitError as e:
            print(e, file=sys.stderr)
            sys.exit(1)

    def add_lock(self, lock_name, lock_type):
        config = configparser.ConfigParser()
        try:
            config.read(self.path / REPO_CONFIG_FILENAME)
            if lock_name in config['locks']:
                print("Lock {} already exists".format(lock_name), file=sys.stderr)
                sys.exit(1)
            else:
                config['locks'][lock_name] = lock_type
        except:
            print("Cannot parse {} in target repository".format(REPO_CONFIG_FILENAME), file=sys.stderr)

        try:
            with open(self.path / REPO_CONFIG_FILENAME, "w") as file:
                config.write(file)

            self._call_git_command_raise(["add", REPO_CONFIG_FILENAME])
            self._call_git_command_raise(["commit", "-m", "add {} lock: {}".format(lock_type, lock_name)])
            self._call_git_command_raise(["push"])
        except GitError as e:
            print(e, file=sys.stderr)
            sys.exit(1)

    def remove_lock(self, lock_name):
        config = configparser.ConfigParser()
        try:
            config.read(self.path / REPO_CONFIG_FILENAME)
            if lock_name not in config['locks']:
                print("Lock {} doesn't exist in repository".format(lock_name), file=sys.stderr)
                sys.exit(1)

            # check if lock is in use
            if lock_name in map(lambda x: x.name, pathlib.Path(self.path).iterdir()):
                print("Failed to remove lock {} which is currently acquired. Release it before removing."
                        .format(lock_name), file=sys.stderr)
                sys.exit(1)

            config['locks'].pop(lock_name)
            with open(self.path / REPO_CONFIG_FILENAME, "w") as file:
                config.write(file)

            self._call_git_command_raise(["add", REPO_CONFIG_FILENAME])
            self._call_git_command_raise(["commit", "-m", "remove lock: {}".format(lock_name)])
            self._call_git_command_raise(["push"])
        except GitError as e:
            print(e, file=sys.stderr)
            sys.exit(1)

    def _lock_acquired(self, lock_name):
        if lock_name not in map(lambda x: x.name, pathlib.Path(self.path).iterdir()):
            return False
        with open(self.path / lock_name, "r") as lock_file:
            content = lock_file.readline()
            return content != 'READ'

    def _num_read_lock_acquired(self, lock_name):
        return len(list(filter(lambda x: x.name.startswith(lock_name + ".read."), pathlib.Path(self.path).iterdir())))

    def acquire(self, lock_name, comment=None, rw_action=None):
        config = configparser.ConfigParser()
        try:
            config.read(self.path / REPO_CONFIG_FILENAME)
            if lock_name not in config['locks']:
                print("Lock {} doesn't exist in repository".format(lock_name), file=sys.stderr)
                sys.exit(1)

            lock_type = config['locks'][lock_name]

            # check if lock is in use
            if lock_type == 'simple' and self._lock_acquired(lock_name):
                print("Lock {} is currently acquired."
                        .format(lock_name), file=sys.stderr)
                sys.exit(1)
            elif lock_type == 'readwrite' and rw_action == 'read':
                if self._lock_acquired(lock_name):
                    print("Write lock of {} is currently acquired."
                            .format(lock_name), file=sys.stderr)
                    sys.exit(1)
            elif lock_type == 'readwrite' and rw_action == 'write':
                if self._lock_acquired(lock_name):
                    print("Write lock of {} is currently acquired."
                            .format(lock_name), file=sys.stderr)
                    sys.exit(1)
                if self._num_read_lock_acquired(lock_name) != 0:
                    print("Read locks of {} are currently acquired."
                            .format(lock_name), file=sys.stderr)
                    sys.exit(1)

            # try to acqurie the lock
            # when acquiring READ lock, also write "READ" into lock1
            # when acquiring WRITE lock, write uuid like usual
            unique_token = str(u.uuid4())

            if lock_type == 'simple' or rw_action == 'write':
                with open(self.path / lock_name, "w") as lock_file:
                    lock_file.write(unique_token)
                self._call_git_command_raise(["add", lock_name])
            elif lock_type == 'readwrite' and rw_action == 'read':
                read_lock_name = lock_name + '.read.' + unique_token
                with open(self.path / read_lock_name, "w") as read_lock_file:
                    read_lock_file.write(unique_token)
                self._call_git_command_raise(["add", read_lock_name])
                with open(self.path / lock_name, "w") as lock_file:
                    lock_file.write("READ")
                self._call_git_command_raise(["add", lock_name])
            else:
                raise RuntimeError("Impossible branch, possibly bug in coding")

            if comment:
                self._call_git_command_raise(["commit", "-m", "acquire lock: {}\n\n{}".format(lock_name, comment)])
            else:
                self._call_git_command_raise(["commit", "-m", "acquire lock: {}".format(lock_name)])

            if self._sync_check_conflict():
                return unique_token
            else:
                print("Lock {} might be currently acquired."
                        .format(lock_name), file=sys.stderr)
                sys.exit(1)
        except GitError as e:
            print(e, file=sys.stderr)
            sys.exit(1)

    # when releasing read, remove lock1.read.{uuid}, if no other read locks acquired, remove lock1 as well
    # when releasing write, remove as usual
    # force releasing a read-write lock is problematic, as we don't know exactly which lock to release
    # we simply emit an error. users should solve it manually
    def release(self, lock_name, uuid=None):
        config = configparser.ConfigParser()
        try:
            config.read(self.path / REPO_CONFIG_FILENAME)
            if lock_name not in config['locks']:
                print("Lock {} doesn't exist in repository".format(lock_name), file=sys.stderr)
                sys.exit(1)

            lock_type = config['locks'][lock_name]

            # check if lock is in use
            if lock_name not in map(lambda x: x.name, pathlib.Path(self.path).iterdir()):
                print("Lock {} is currently not acquired."
                        .format(lock_name), file=sys.stderr)
                sys.exit(1)
            else:
                release_read_lock = None
                if uuid:
                    with open(self.path / lock_name, "r") as lock_file:
                        old_uuid = lock_file.readline()
                        if old_uuid == 'READ':
                            # in this case uuid should be in the reader lock
                            # check the existence of lock_name.read.{uuid}
                            read_lock_name = lock_name + '.read.' + uuid
                            if read_lock_name not in map(lambda x: x.name, pathlib.Path(self.path).iterdir()):
                                print("No reader lock in uuid: {}".format(uuid))
                                sys.exit(1)
                            release_read_lock = read_lock_name
                        elif uuid != old_uuid:
                            print("Cannot release lock {}, acquired by another uuid: {}".format(lock_name,old_uuid),
                                  file=sys.stderr)
                            sys.exit(1)
                elif lock_type == 'readwrite':
                    print("Read-write lock {} cannot be force-released, try doing it manually".format(lock_name),
                            file=sys.stderr)
                    sys.exit(1)

                if release_read_lock:
                    self._call_git_command_raise(["rm", release_read_lock])
                    # if all read lock is removed
                    if self._num_read_lock_acquired(lock_name) == 0:
                        self._call_git_command_raise(["rm", lock_name])
                    self._call_git_command_raise(["commit", "-m", "release read lock: {} in uuid: {}"
                                                  .format(release_read_lock, uuid)])
                else:
                    self._call_git_command_raise(["rm", lock_name])
                    self._call_git_command_raise(["commit", "-m", "release lock: {}".format(lock_name)])
                if not self._sync_check_conflict():
                    print("Lock {} cannot be released."
                          .format(lock_name), file=sys.stderr)
                    sys.exit(1)
        except GitError as e:
            print(e, file=sys.stderr)
            sys.exit(1)

def env_get_git_options():
    arg_str = os.getenv("SLIG_GIT_OPTIONS")
    if arg_str:
        return shlex.split(arg_str)
    else:
        return []

def env_get_repo():
    repo_str = os.getenv("SLIG_GIT_REPO")
    if not repo_str:
        sys.exit("SLIG_GIT_REPO is not specified")
    return repo_str


def setup_argparse():
    parser = argparse.ArgumentParser(description='')
    subparsers = parser.add_subparsers(title="actions")

    setup_repo_subparser(subparsers)
    setup_locks_subparser(subparsers)
    setup_acquire_subparser(subparsers)
    setup_release_subparser(subparsers)

    return parser


def setup_repo_subparser(subparsers):
    repo = subparsers.add_parser("repo", help="remote repository setup")
    repo.set_defaults(action="repo")
    repo_subparsers = repo.add_subparsers(title="repo actions")

    repo_init = repo_subparsers.add_parser("init", help="initialize the remote repository")
    repo_init.set_defaults(repo_action="init")


def setup_locks_subparser(subparsers):
    locks = subparsers.add_parser("locks", help="manage lock definitions")
    locks.set_defaults(action="locks")
    locks_subparsers = locks.add_subparsers(title="locks actions")

    locks_add = locks_subparsers.add_parser("add", help="add a lock")
    locks_add.set_defaults(locks_action="add")
    locks_add.add_argument("lock_name", help="name of lock to add")
    locks_add.add_argument("--simple", action="store_true", help="simple locking (default)")
    locks_add.add_argument("--readwrite", action="store_true", help="reader-writer locking")

    locks_delete = locks_subparsers.add_parser("delete", help="delete a lock")
    locks_delete.set_defaults(locks_action="delete")
    locks_delete.add_argument("lock_name", help="name of lock to delete")

def setup_acquire_subparser(subparsers):
    parser_acquire = subparsers.add_parser("acquire", help="acquire a lock")
    parser_acquire.set_defaults(action="acquire")
    parser_acquire.add_argument("lock_name", help="name of lock")
    parser_acquire.add_argument("-c", "--comment", dest="comment", help="comments to write into commit message")
    parser_acquire.add_argument("--read", action="store_true", help="comments to write into commit message")
    parser_acquire.add_argument("--write", action="store_true", help="comments to write into commit message")

def setup_release_subparser(subparsers):
    parser_release = subparsers.add_parser("release", help="release a lock")
    parser_release.set_defaults(action="release")
    parser_release.add_argument("lock_name", help="name of lock")
    parser_release.add_argument("-u", "--uuid", dest="uuid",
                                help="uuid of lock (when not using --force)")
    parser_release.add_argument("-f", "--force", action="store_true",
                                help="force releasing the lock without providing its uuid")

if __name__ == "__main__":
    parser = setup_argparse()
    args = parser.parse_args()
    remote = env_get_repo()
    git_options = env_get_git_options()

    # TODO: refactor arg handling
    if args.action == "repo" and args.repo_action == 'init':
        repo = ClonedGitRepo(remote, git_options)
        repo.initialize()
    elif args.action == "locks" and args.locks_action == 'add' and args.lock_name:
        repo = ClonedGitRepo(remote, git_options)
        if args.readwrite and not args.simple:
            repo.add_lock(args.lock_name, lock_type="readwrite")
        elif args.readwrite and args.simple:
            parser.print_help()
        else:
            repo.add_lock(args.lock_name, lock_type="simple")
    elif args.action == "locks" and args.locks_action == 'delete' and args.lock_name:
        repo = ClonedGitRepo(remote, git_options)
        repo.remove_lock(args.lock_name)
    elif args.action == "acquire" and args.lock_name:
        repo = ClonedGitRepo(remote, git_options)
        if args.read and not args.write:
            uuid = repo.acquire(args.lock_name, args.comment, rw_action="read")
            print(uuid)  # print uuid of the lock to stdout
        elif args.write and not args.read:
            uuid = repo.acquire(args.lock_name, args.comment, rw_action="write")
            print(uuid)  # print uuid of the lock to stdout
        elif args.write and args.read:
            parser.print_help()
        else:
            uuid = repo.acquire(args.lock_name, args.comment)
            print(uuid)  # print uuid of the lock to stdout
    elif args.action == "release" and args.lock_name and args.uuid and not args.force:
        repo = ClonedGitRepo(remote, git_options)
        repo.release(args.lock_name, args.uuid)
    elif args.action == "release" and args.lock_name and not args.uuid and args.force:
        repo = ClonedGitRepo(remote, git_options)
        repo.release(args.lock_name)
    else:
        parser.print_help()
