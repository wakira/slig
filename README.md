# slig
slig - Simple Locking In your Git repo

## Runtime Dependencies

* git
* util-linux (for uuidgen)

## Usage

SLIG_GIT_REPO=... (git url format)

slig repo {init | upgrade}

slig locks {add | delete | set}

IN THE REPOSITORY:

slig.ini:

[locks]
lock1=simple
lock2=readers-writer
[metadata]
version=1.0

slig acquire LOCKNAME [--repo REPO]

slig release LOCKNAME [UUID] [--force]

## Output
Git's output writes to stderr
Additional error messages are also written to stderr

Result of normal operations (like uuid) is written to stdout

## Atomicity

The git flow

### Acquire

User supplies lock's name

```
clone remote to random-generated dir -> test -f XXX.lock -> fail if exist
                                        +-----------------> success if not exist -> add file (write uid to content) -> commit -> push -> fail -> pull --rebase -> success -> try push again (recursive),
                                                                                                                                 |               +--------------> conflict -> fail (lock acquired by others)
                                                                                                                                 +-----> success
```

Upon success, uuid is printed out. The uuid is neccessary for release.

### Release

User supplies lock's name and uuid (printed out by Acquire)

```
clone remote to random-generated dir -> test -f XXX.lock -> fail if not exist
                                        +-----------------> check content matches uid -> fail if mismatch
                                                            +--------------------------> success if match -> git rm XXX.lock -> commit -> push -> fail -> pull --rebase -> success try push again (recursive)
                                                                                                                                          |               +--------------> conflict -> impossible! setup is corrupted!
                                                                                                                                          +-----> success
```

### Force-Release

Behaves like release besides uuid is not checked
