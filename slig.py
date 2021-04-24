import argparse
import sys
import os
import tempfile
import subprocess
import shlex
import pathlib
import configparser


REPO_CONFIG_FILENAME = "slig.ini"


def file_exist(path):
    pass


def lock_file_check(path, uuid):
    pass


class RepoConfig():
    def __init__(self):
        self.config = configparser.ConfigParser()

    def load(self, repo_path):
        # TODO:
        pass

    def save(self, repo_path):
        # TODO:
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
        print(clone_result.stderr.decode(sys.stderr.encoding), file=sys.stderr)  # write stderr of git to stderr
        if clone_result.returncode == 0:
            subdirs = list(pathlib.Path(parent_dir).iterdir())
            if len(subdirs) == 1:
                self.name = subdirs[0].name
                self.path = pathlib.Path(parent_dir) / self.name
                print(self.path)
            else:
                raise RuntimeError("Cannot find cloned repository at {}".format(parent_dir))
        else:
            raise RuntimeError('Cannot clone remote repository "{}" with git options {}'.format(remote, git_options))

    def _call_git_command(self, commands):
        result = subprocess.run(["git"] + self._git_options + commands, cwd=self.path, capture_output=True)
        decoded_stderr = result.stderr.decode(sys.stderr.encoding)
        print(decoded_stderr, file=sys.stderr)  # write stderr of git to stderr
        return (result.returncode, decoded_stderr)

    def _call_git_command_raise(self, commands):
        (returncode, decoded_stderr) = self._call_git_command(commands)
        if returncode != 0:
            raise GitError(returncode, decoded_stderr)

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
            self._call_git_command_raise(["commit", "-m", "'initialize slig repository"])
            self._call_git_command_raise(["push"])
        except GitError as e:
            print(e, file=sys.stderr)
            print(e.stderr, file=sys.stderr)
        except Exception as e:
            print(e, file=sys.stderr)

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
            self._call_git_command_raise(["commit", "-m", "'add {} lock: {}".format("simple", lock_name)])
            self._call_git_command_raise(["push"])
        except GitError as e:
            print(e, file=sys.stderr)
            print(e.stderr, file=sys.stderr)
        except Exception as e:
            print(e, file=sys.stderr)

    def remove_lock(self, lock_name):
        config = configparser.ConfigParser()
        try:
            config.read(self.path / REPO_CONFIG_FILENAME)
            if lock_name not in config['locks']:
                print("Lock {} doesn't exist in repository".format(lock_name), file=sys.stderr)
                sys.exit(1)

            # check if lock is in use
            if lock_name in list(pathlib.Path(self.path).iterdir()):
                print("Failed to remove lock {} which is currently acquired. Release it before removing."
                        .format(lock_name), file=sys.stderr)
                sys.exit(1)

            config['locks'].pop(lock_name)
            with open(self.path / REPO_CONFIG_FILENAME, "w") as file:
                config.write(file)

            self._call_git_command_raise(["add", REPO_CONFIG_FILENAME])
            self._call_git_command_raise(["commit", "-m", "'remove lock: {}".format(lock_name)])
            self._call_git_command_raise(["push"])
        except GitError as e:
            print(e, file=sys.stderr)
            print(e.stderr, file=sys.stderr)
        except Exception as e:
            print(e, file=sys.stderr)

    def acquire(self, lock_name):
        # TODO: start here
        pass


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
    parser_release.add_argument("uuid", help="uuid of lock or name of lock (with --force)")
    parser_release.add_argument("--force", help="uuid of lock or name of lock (with --force)")

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
    elif args.action == "release" and not args.force:
        # TODO:
        pass
    elif args.action == "release" and args.force:
        # TODO:
        pass
    else:
        parser.print_help()
