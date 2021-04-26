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


def file_exist(path):
    pass


def lock_file_check(path, uuid):
    pass


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
                print("DEBUG:", self.path)
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

    def add_lock(self, lock_name):
        config = configparser.ConfigParser()
        try:
            config.read(self.path / REPO_CONFIG_FILENAME)
            if lock_name in config['locks']:
                # FIXME: what to do if lock_name already exists?
                pass
            else:
                config['locks'][lock_name] = 'simple'  # TODO: currently only simple lock is supported
        except:
            print("Cannot parse {} in target repository".format(REPO_CONFIG_FILENAME), file=sys.stderr)

        try:
            with open(self.path / REPO_CONFIG_FILENAME, "w") as file:
                config.write(file)

            self._call_git_command_raise(["add", REPO_CONFIG_FILENAME])
            # TODO: currently only simple lock is supported
            self._call_git_command_raise(["commit", "-m", "add {} lock: {}".format("simple", lock_name)])
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

    # TODO: add option to add description to this operation
    def acquire(self, lock_name):
        config = configparser.ConfigParser()
        try:
            config.read(self.path / REPO_CONFIG_FILENAME)
            if lock_name not in config['locks']:
                print("Lock {} doesn't exist in repository".format(lock_name), file=sys.stderr)
                sys.exit(1)

            # check if lock is in use
            if lock_name in map(lambda x: x.name, pathlib.Path(self.path).iterdir()):
                print("Lock {} is currently acquired."
                        .format(lock_name), file=sys.stderr)
                sys.exit(1)
            else:
                # try to acqurie the lock
                with open(self.path / lock_name, "w") as lock_file:
                    unique_token = str(u.uuid4())
                    lock_file.write(unique_token)
                    self._call_git_command_raise(["add", lock_name])
                    self._call_git_command_raise(["commit", "-m", "acquire lock: {}".format(lock_name)])

                    if self._sync_check_conflict():
                        return unique_token
                    else:
                        print("Lock {} might be currently acquired."
                              .format(lock_name), file=sys.stderr)
                        sys.exit(1)

                # TODO: control should never reach here?
                raise RuntimeError("Error acquiring lock")
        except GitError as e:
            print(e, file=sys.stderr)
            sys.exit(1)

    def release(self, lock_name, uuid=None):
        config = configparser.ConfigParser()
        try:
            config.read(self.path / REPO_CONFIG_FILENAME)
            if lock_name not in config['locks']:
                print("Lock {} doesn't exist in repository".format(lock_name), file=sys.stderr)
                sys.exit(1)

            # check if lock is in use
            if lock_name not in map(lambda x: x.name, pathlib.Path(self.path).iterdir()):
                print("Lock {} is currently not acquired."
                        .format(lock_name), file=sys.stderr)
                sys.exit(1)
            else:
                if uuid:
                    with open(self.path / lock_name, "r") as lock_file:
                        old_uuid = lock_file.readline()
                        if uuid != old_uuid:
                            print("Cannot release lock {}, acquired by another uuid: {}".format(lock_name,uuid),
                                  file=sys.stderr)
                            sys.exit(1)
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

    locks_delete = locks_subparsers.add_parser("delete", help="delete a lock")
    locks_delete.set_defaults(locks_action="delete")
    locks_delete.add_argument("lock_name", help="name of lock to delete")

def setup_acquire_subparser(subparsers):
    parser_acquire = subparsers.add_parser("acquire", help="acquire a lock")
    parser_acquire.set_defaults(action="acquire")
    parser_acquire.add_argument("lock_name", help="name of lock")

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

    if args.action == "repo" and args.repo_action == 'init':
        repo = ClonedGitRepo(remote, git_options)
        repo.initialize()
    elif args.action == "locks" and args.locks_action == 'add' and args.lock_name:
        repo = ClonedGitRepo(remote, git_options)
        repo.add_lock(args.lock_name)
    elif args.action == "locks" and args.locks_action == 'delete' and args.lock_name:
        repo = ClonedGitRepo(remote, git_options)
        repo.remove_lock(args.lock_name)
    elif args.action == "acquire" and args.lock_name:
        repo = ClonedGitRepo(remote, git_options)
        uuid = repo.acquire(args.lock_name)
        print(uuid)  # print uuid of the lock to stdout
    elif args.action == "release" and args.lock_name and args.uuid and not args.force:
        repo = ClonedGitRepo(remote, git_options)
        uuid = repo.release(args.lock_name, args.uuid)
    elif args.action == "release" and args.lock_name and not args.uuid and args.force:
        repo = ClonedGitRepo(remote, git_options)
        uuid = repo.release(args.lock_name)
    else:
        parser.print_help()
