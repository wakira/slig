# slig - Simple Locking In your Git repo

slig is a simple lock manager for protecting access to shared resources.
It utilizes a (remote) git repository to maintain lock states and history.

Slig is best used for non performance-critical situations, such as coordinating
manual tasks or periodic script executions across multiple machines.
Slig provides a simple interface that can be easily integrated into shell scripts.

## Runtime Dependencies

* git executable in PATH

## Usage

Make sure that environment variable `SLIG_GIT_REPO` is set to git repository's remote URL
before calling each slig commands.

Initialize slig repository (you need only do this once):
```sh
slig repo init
```

Register a lock that you can `acquire` later:
```sh
slig locks {add | delete} [lock-name]
```

Acquire a lock:
```sh
slig acquire [lock-name]
```
Upon success, the uuid of the lock will be print to stdout

Release a lock:
```sh
slig release [lock-name] --uuid [uuid]
```

Force-release a lock without providing uuid (be careful, you can release a log that is not acquired by you!):
```sh
slig release [lock-name] --force
```

## Output
Return code 0 indicates successful execution and 1 indicates error

Git's output writes to stderr

Additional error messages are also written to stderr

Result of normal operations (like uuid) is written to stdout

## Atomicity

Git's conflict checking mechanism assures a single lock cannot be acquired by multiple clients at the same time

### Acquire

User supplies lock's name

```
clone remote to random-generated dir -> check lock acquired -> fail if yes
                                        +--------------------> success -> add lock file (write uuid to content) -> commit -> push -> fail -> pull --rebase -> success -> try push again (recursive)
                                                                                                                               |             +--------------> conflict -> fail (lock acquired by others)
                                                                                                                               +-----> success
```

Upon success, uuid is printed out. The uuid is neccessary for release.

### Release

User supplies lock's name and uuid

```
clone remote to random-generated dir -> check lock acquired -> fail if not
                                        +--------------------> check content matches uuid -> fail if mismatch
                                                               +---------------------------> success if match -> git rm XXX -> commit -> push -> fail -> pull --rebase -> success try push again (recursive)
                                                                                                                                         |               +--------------> conflict -> impossible! setup is corrupted!
                                                                                                                                         +-----> success
```
