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
slig locks {add | delete} LOCK-NAME] [{--simple | --readwrite}]
```

Acquire a lock:
```sh
slig acquire LOCK-NAME [{--read | --write}]
```
Upon success, the uuid of the lock will be print to stdout

Release a lock:
```sh
slig release LOCK-NAME --uuid UUID
```

Force-release a lock without providing uuid (be careful, you can release a log that is not acquired by you!):
```sh
slig release LOCK-NAME --force
```

## Output
Return code 0 indicates successful execution and 1 indicates error

Git's output writes to stderr

Additional error messages are also written to stderr

Result of normal operations (like uuid) is written to stdout

## Atomicity

Git's conflict checking mechanism assures a single lock cannot be acquired by multiple clients at the same time

Below is a brief introduction to how slig works.

### Acquiring a simple lock

User supplies lock's name

```
clone remote to random-generated dir -> check lock acquired -> fail if yes
                                        +--------------------> success -> add lock file (write uuid to content) -> commit -> push -> fail -> pull --rebase -> success -> try push again (recursive)
                                                                                                                               |             +--------------> conflict -> fail (lock acquired by others)
                                                                                                                               +-----> success
```

The lock is presented as a file named `LOCK-NAME`, it's content being `UUID`.

Upon success, uuid is printed out. The uuid is neccessary for release.

### Releasing a simple lock

User supplies lock's name and uuid

```
clone remote to random-generated dir -> check lock acquired -> fail if not
                                        +--------------------> check content matches uuid -> fail if mismatch
                                                               +---------------------------> success if match -> git rm XXX -> commit -> push -> fail -> pull --rebase -> success try push again (recursive)
                                                                                                                                         |               +--------------> conflict -> impossible! setup is corrupted!
                                                                                                                                         +-----> success
```

### Reader-writer lock

The general flow is the same with a simple lock. However, read-locks are stored separately in the file
`LOCK-NAME.read.UUID`. Write-lock is stored in `LOCK-NAME` (the same as simple lock), but if any read-locks
are required, content `READ` is written to `LOCK-NAME` to block the acquiring of write-lock.
