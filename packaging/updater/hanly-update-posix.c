/*
 * The one step of a macOS or Linux update that cannot be done from Python.
 *
 * By the time this runs the new installation has already been built and
 * proved. What is left is to wait for the old Hanly to stop, exchange two
 * directories durably, start the new build, and wait for it to say - with the
 * exact bytes this transaction will accept and no others - that it came up.
 * If it does not, the old installation goes back.
 *
 * It is written in C and linked against nothing but the system because it has
 * to work when the thing it is repairing does not: the installation is briefly
 * absent between the two renames, and a helper that loaded an interpreter, a
 * library, or a script out of that directory would be relying on the very tree
 * it is replacing.
 *
 * It is not a general updater. It parses no archives, computes no differences,
 * opens no network connection, and reads no format but the fixed descriptor
 * below, which Python writes privately for one transaction.
 *
 * Build: cc -std=c11 -Wall -Wextra -Werror -O2 -o hanly-update-posix
 *            hanly-update-posix.c
 */

#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#if defined(__APPLE__)
#include <libproc.h>
#endif

/* ------------------------------------------------------------------ wire -- */

#define DESCRIPTOR_MAGIC "HANLYUPD"
#define DESCRIPTOR_MAGIC_LENGTH 8
#define DESCRIPTOR_VERSION 1u
#define DESCRIPTOR_MAX_BYTES (64u * 1024u)
#define FIELD_MAX_BYTES 4096u

/* Every field, in the order the descriptor carries them. Adding one is a
 * change to both sides at once; a descriptor with any other count is refused
 * rather than read as far as it happens to agree. */
enum {
    FIELD_TRANSACTION = 0,
    FIELD_LOCK,
    FIELD_INSTALL,
    FIELD_STAGING,
    FIELD_CANDIDATE,
    FIELD_BACKUP,
    FIELD_REJECTED,
    FIELD_RESULT,
    FIELD_ACK,
    FIELD_CHALLENGE,
    FIELD_EXPECTED,
    FIELD_EXECUTABLE,
    FIELD_LAUNCH,
    FIELD_PARENT_PID,
    FIELD_EXIT_TIMEOUT,
    FIELD_READY_TIMEOUT,
    FIELD_INSTALL_DEVICE,
    FIELD_INSTALL_INODE,
    FIELD_CANDIDATE_DEVICE,
    FIELD_CANDIDATE_INODE,
    FIELD_COUNT
};

/* Outcomes, written as one word into the result file. Python reads these; so
 * does a person, which is why they are words and not numbers. */
#define RESULT_COMMITTED "committed"
#define RESULT_RESTORED "restored"
#define RESULT_RECOVERY "recovery-required"
#define RESULT_ABANDONED "abandoned"

#define EXIT_OK 0
#define EXIT_FAILED 1
#define EXIT_UNUSABLE 2

#define LAUNCH_OPEN "open"
#define LAUNCH_EXEC "exec"

#define OPEN_TOOL "/usr/bin/open"

/* How often the two waiting loops look again. One second is far below any
 * timeout here and far above the cost of the check. */
#define POLL_SECONDS 1

struct descriptor {
    char *fields[FIELD_COUNT];
    size_t lengths[FIELD_COUNT];
};

static const char *program_name = "hanly-update-posix";

static void note(const char *message, const char *detail)
{
    if (detail != NULL) {
        fprintf(stderr, "%s: %s: %s\n", program_name, message, detail);
    } else {
        fprintf(stderr, "%s: %s\n", program_name, message);
    }
}

/* ----------------------------------------------------------- descriptor -- */

static void descriptor_free(struct descriptor *plan)
{
    for (int index = 0; index < FIELD_COUNT; index++) {
        free(plan->fields[index]);
        plan->fields[index] = NULL;
    }
}

static bool read_u32(const unsigned char *data, size_t size, size_t *offset, uint32_t *value)
{
    if (size - *offset < 4) {
        return false;
    }
    *value = (uint32_t)data[*offset] << 24 | (uint32_t)data[*offset + 1] << 16 |
             (uint32_t)data[*offset + 2] << 8 | (uint32_t)data[*offset + 3];
    *offset += 4;
    return true;
}

/*
 * Read the whole descriptor, or refuse it. Every length is checked against
 * what is left rather than against what it claims, a field may not contain a
 * NUL, and a descriptor with bytes after its last field is rejected outright:
 * trailing data means the writer and this reader do not agree.
 */
static bool descriptor_parse(const unsigned char *data, size_t size, struct descriptor *plan)
{
    memset(plan, 0, sizeof(*plan));
    if (size < DESCRIPTOR_MAGIC_LENGTH + 8) {
        note("the update descriptor is too short", NULL);
        return false;
    }
    if (memcmp(data, DESCRIPTOR_MAGIC, DESCRIPTOR_MAGIC_LENGTH) != 0) {
        note("the update descriptor is not one of ours", NULL);
        return false;
    }

    size_t offset = DESCRIPTOR_MAGIC_LENGTH;
    uint32_t version = 0;
    uint32_t count = 0;
    if (!read_u32(data, size, &offset, &version) || !read_u32(data, size, &offset, &count)) {
        return false;
    }
    if (version != DESCRIPTOR_VERSION || count != (uint32_t)FIELD_COUNT) {
        note("the update descriptor was written by a different Hanly", NULL);
        return false;
    }

    for (uint32_t index = 0; index < count; index++) {
        uint32_t length = 0;
        if (!read_u32(data, size, &offset, &length)) {
            note("the update descriptor ends inside a field", NULL);
            descriptor_free(plan);
            return false;
        }
        if (length > FIELD_MAX_BYTES || length > size - offset) {
            note("the update descriptor declares a field longer than it carries", NULL);
            descriptor_free(plan);
            return false;
        }
        char *value = malloc((size_t)length + 1);
        if (value == NULL) {
            descriptor_free(plan);
            return false;
        }
        memcpy(value, data + offset, length);
        value[length] = '\0';
        if (memchr(value, '\0', length) != NULL) {
            note("the update descriptor has a field containing a null byte", NULL);
            free(value);
            descriptor_free(plan);
            return false;
        }
        plan->fields[index] = value;
        plan->lengths[index] = length;
        offset += length;
    }

    if (offset != size) {
        note("the update descriptor has trailing data", NULL);
        descriptor_free(plan);
        return false;
    }
    return true;
}

static bool descriptor_read(const char *path, struct descriptor *plan)
{
    int handle = open(path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if (handle < 0) {
        note("could not open the update descriptor", path);
        return false;
    }

    struct stat status;
    if (fstat(handle, &status) != 0 || !S_ISREG(status.st_mode) ||
        (uintmax_t)status.st_size > DESCRIPTOR_MAX_BYTES) {
        note("the update descriptor is not a small regular file", path);
        close(handle);
        return false;
    }

    size_t size = (size_t)status.st_size;
    unsigned char *data = malloc(size > 0 ? size : 1);
    if (data == NULL) {
        close(handle);
        return false;
    }

    size_t read_total = 0;
    while (read_total < size) {
        ssize_t chunk = read(handle, data + read_total, size - read_total);
        if (chunk <= 0) {
            note("could not read the update descriptor", path);
            free(data);
            close(handle);
            return false;
        }
        read_total += (size_t)chunk;
    }
    close(handle);

    bool parsed = descriptor_parse(data, size, plan);
    free(data);
    return parsed;
}

static long long field_number(const struct descriptor *plan, int field)
{
    errno = 0;
    char *end = NULL;
    long long value = strtoll(plan->fields[field], &end, 10);
    if (errno != 0 || end == plan->fields[field] || *end != '\0' || value < 0) {
        return -1;
    }
    return value;
}

/* ------------------------------------------------------------ filesystem -- */

/* A rename is only durable once the directory entry itself has been flushed,
 * so every mutation below is followed by a sync of the directory it changed. */
static bool sync_directory(const char *path)
{
    int handle = open(path, O_RDONLY | O_CLOEXEC
#ifdef O_DIRECTORY
                                | O_DIRECTORY
#endif
    );
    if (handle < 0) {
        return false;
    }
    bool flushed = fsync(handle) == 0;
    close(handle);
    return flushed;
}

static bool parent_of(const char *path, char *buffer, size_t size)
{
    size_t length = strlen(path);
    while (length > 1 && path[length - 1] == '/') {
        length--;
    }
    while (length > 0 && path[length - 1] != '/') {
        length--;
    }
    if (length == 0) {
        return false;
    }
    if (length > 1) {
        length--;
    }
    if (length + 1 > size) {
        return false;
    }
    memcpy(buffer, path, length);
    buffer[length] = '\0';
    return true;
}

static bool sync_parent(const char *path)
{
    char parent[PATH_MAX];
    return parent_of(path, parent, sizeof(parent)) && sync_directory(parent);
}

static bool directory_present(const char *path)
{
    struct stat status;
    return lstat(path, &status) == 0 && S_ISDIR(status.st_mode);
}

/*
 * A directory this transaction recorded, still the same directory. Identity is
 * the device and inode written before anything moved, not the path: the path
 * is what an attacker or an accident can make point somewhere else.
 */
static bool identity_matches(const char *path, long long device, long long inode)
{
    struct stat status;
    if (lstat(path, &status) != 0 || !S_ISDIR(status.st_mode)) {
        return false;
    }
    return (long long)status.st_dev == device && (long long)status.st_ino == inode;
}

static bool move_directory(const char *from, const char *to)
{
    if (rename(from, to) != 0) {
        note("could not move a directory into place", from);
        return false;
    }
    sync_parent(from);
    sync_parent(to);
    return true;
}

static bool write_result(const struct descriptor *plan, const char *outcome, const char *detail)
{
    char temporary[PATH_MAX];
    int written = snprintf(temporary, sizeof(temporary), "%s.partial", plan->fields[FIELD_RESULT]);
    if (written < 0 || (size_t)written >= sizeof(temporary)) {
        return false;
    }

    int handle = open(temporary, O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (handle < 0) {
        return false;
    }
    FILE *stream = fdopen(handle, "w");
    if (stream == NULL) {
        close(handle);
        return false;
    }
    fprintf(stream, "%s\n%s\n", outcome, detail != NULL ? detail : "");
    fflush(stream);
    bool flushed = fsync(fileno(stream)) == 0;
    fclose(stream);

    if (!flushed || rename(temporary, plan->fields[FIELD_RESULT]) != 0) {
        unlink(temporary);
        return false;
    }
    sync_parent(plan->fields[FIELD_RESULT]);
    return true;
}

/* ---------------------------------------------------------------- claim --- */

/*
 * One helper per installation, for as long as it runs. The lock is advisory
 * and held on an open handle, so it is released by the kernel if this process
 * dies - which is what makes a crashed helper recoverable instead of
 * permanent.
 */
static int claim_lock(const char *path)
{
    int handle = open(path, O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (handle < 0) {
        note("could not open the update lock", path);
        return -1;
    }
    if (flock(handle, LOCK_EX | LOCK_NB) != 0) {
        note("another update is already running for this installation", path);
        close(handle);
        return -1;
    }
    char claim[64];
    int written = snprintf(claim, sizeof(claim), "%ld\n", (long)getpid());
    if (written > 0) {
        if (ftruncate(handle, 0) == 0 && lseek(handle, 0, SEEK_SET) == 0) {
            ssize_t ignored = write(handle, claim, (size_t)written);
            (void)ignored;
        }
        fsync(handle);
    }
    return handle;
}

/* ------------------------------------------------------------ processes --- */

static bool path_inside(const char *candidate, const char *root)
{
    size_t length = strlen(root);
    if (length == 0 || strncmp(candidate, root, length) != 0) {
        return false;
    }
    return candidate[length] == '/' || candidate[length] == '\0';
}

#if defined(__APPLE__)
/* By the program each process is actually running, never by its name: the
 * shell, the Control Center and the lookup child all run this installation's
 * executable, and anything else called hanly-desktop is none of our business. */
static int processes_under(const char *root, pid_t *found, int limit)
{
    int capacity = proc_listpids(PROC_ALL_PIDS, 0, NULL, 0);
    if (capacity <= 0) {
        return -1;
    }
    pid_t *pids = malloc((size_t)capacity);
    if (pids == NULL) {
        return -1;
    }
    int bytes = proc_listpids(PROC_ALL_PIDS, 0, pids, capacity);
    if (bytes <= 0) {
        free(pids);
        return -1;
    }

    int count = 0;
    int total = bytes / (int)sizeof(pid_t);
    char program[PROC_PIDPATHINFO_MAXSIZE];
    for (int index = 0; index < total && count < limit; index++) {
        if (pids[index] <= 0) {
            continue;
        }
        if (proc_pidpath(pids[index], program, sizeof(program)) <= 0) {
            continue;
        }
        if (path_inside(program, root)) {
            found[count++] = pids[index];
        }
    }
    free(pids);
    return count;
}
#else
static int processes_under(const char *root, pid_t *found, int limit)
{
    DIR *processes = opendir("/proc");
    if (processes == NULL) {
        return -1;
    }

    int count = 0;
    struct dirent *entry;
    while ((entry = readdir(processes)) != NULL && count < limit) {
        char *end = NULL;
        long value = strtol(entry->d_name, &end, 10);
        if (end == entry->d_name || *end != '\0' || value <= 0) {
            continue;
        }
        char link[PATH_MAX];
        char program[PATH_MAX];
        int written = snprintf(link, sizeof(link), "/proc/%ld/exe", value);
        if (written < 0 || (size_t)written >= sizeof(link)) {
            continue;
        }
        ssize_t length = readlink(link, program, sizeof(program) - 1);
        if (length <= 0) {
            continue;
        }
        program[length] = '\0';
        if (path_inside(program, root)) {
            found[count++] = (pid_t)value;
        }
    }
    closedir(processes);
    return count;
}
#endif

#define MAX_TRACKED_PROCESSES 256

static bool installation_is_free(const char *root, pid_t parent)
{
    if (parent > 0 && kill(parent, 0) == 0) {
        return false;
    }
    pid_t found[MAX_TRACKED_PROCESSES];
    int count = processes_under(root, found, MAX_TRACKED_PROCESSES);
    /* Inspection failing is not the same as nothing running. Refusing to act
     * on an unknown answer is the whole point of asking. */
    return count == 0;
}

static bool wait_for_exit(const char *root, pid_t parent, long long seconds)
{
    for (long long waited = 0; waited <= seconds; waited += POLL_SECONDS) {
        if (installation_is_free(root, parent)) {
            return true;
        }
        sleep(POLL_SECONDS);
    }
    return installation_is_free(root, parent);
}

static void stop_processes_under(const char *root)
{
    pid_t found[MAX_TRACKED_PROCESSES];
    for (int attempt = 0; attempt < 2; attempt++) {
        int count = processes_under(root, found, MAX_TRACKED_PROCESSES);
        if (count <= 0) {
            return;
        }
        for (int index = 0; index < count; index++) {
            kill(found[index], attempt == 0 ? SIGTERM : SIGKILL);
        }
        sleep(POLL_SECONDS);
    }
}

/* ---------------------------------------------------------------- launch -- */

/*
 * Start Hanly and come straight back.
 *
 * Two forks, not one. The grandchild becomes the application and is reparented
 * away, so nothing here waits on a program that is meant to keep running: what
 * this helper waits for is the acknowledgement, and a single fork would leave
 * it blocked in waitpid until the user quit Hanly instead.
 */
static void redirect_standard_streams(void)
{
    int null = open("/dev/null", O_RDWR | O_CLOEXEC);
    if (null < 0) {
        return;
    }
    dup2(null, STDIN_FILENO);
    dup2(null, STDOUT_FILENO);
    dup2(null, STDERR_FILENO);
    if (null > STDERR_FILENO) {
        close(null);
    }
}

static bool launch_detached(const struct descriptor *plan, bool acknowledging)
{
    char program[PATH_MAX];

    pid_t child = fork();
    if (child < 0) {
        note("could not start the installation", NULL);
        return false;
    }
    if (child > 0) {
        /* The middle child exits at once; reaping it leaves no zombie. */
        int status = 0;
        waitpid(child, &status, 0);
        return true;
    }

    setsid();
    if (fork() != 0) {
        _exit(EXIT_OK);
    }

    /* The application keeps running for as long as the user keeps it open, and
     * would otherwise hold this helper's streams - and whatever started the
     * helper - open for exactly that long. */
    redirect_standard_streams();

    if (strcmp(plan->fields[FIELD_LAUNCH], LAUNCH_OPEN) == 0) {
        /* ``open -n`` asks LaunchServices for a new instance, which is what
         * makes the relaunched build a real application with a Dock entry.
         * Running the program inside the bundle directly does not. */
        if (acknowledging) {
            execl(OPEN_TOOL, OPEN_TOOL, "-n", plan->fields[FIELD_INSTALL], "--args",
                  "--update-ready-v2", plan->fields[FIELD_CHALLENGE], (char *)NULL);
        } else {
            execl(OPEN_TOOL, OPEN_TOOL, "-n", plan->fields[FIELD_INSTALL], (char *)NULL);
        }
    } else {
        int written = snprintf(program, sizeof(program), "%s/%s", plan->fields[FIELD_INSTALL],
                               plan->fields[FIELD_EXECUTABLE]);
        if (written > 0 && (size_t)written < sizeof(program)) {
            if (acknowledging) {
                execl(program, program, "--update-ready-v2", plan->fields[FIELD_CHALLENGE],
                      (char *)NULL);
            } else {
                execl(program, program, (char *)NULL);
            }
        }
    }
    _exit(EXIT_FAILED);
}

static bool launch_candidate(const struct descriptor *plan)
{
    return launch_detached(plan, true);
}

static void launch_restored(const struct descriptor *plan)
{
    launch_detached(plan, false);
}

/* ------------------------------------------------------- acknowledgement -- */

/*
 * The answer is compared as whole bytes against what the installer decided
 * this transaction would accept. A version number, a stale file from an
 * earlier attempt, or a build with a different identity all fail the same way:
 * they are not these bytes.
 */
static bool acknowledgement_matches(const struct descriptor *plan)
{
    int handle = open(plan->fields[FIELD_ACK], O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if (handle < 0) {
        return false;
    }

    struct stat status;
    size_t expected = plan->lengths[FIELD_EXPECTED];
    if (fstat(handle, &status) != 0 || !S_ISREG(status.st_mode) ||
        (uintmax_t)status.st_size != (uintmax_t)expected) {
        close(handle);
        return false;
    }

    char *answered = malloc(expected > 0 ? expected : 1);
    if (answered == NULL) {
        close(handle);
        return false;
    }

    size_t read_total = 0;
    while (read_total < expected) {
        ssize_t chunk = read(handle, answered + read_total, expected - read_total);
        if (chunk <= 0) {
            break;
        }
        read_total += (size_t)chunk;
    }
    close(handle);

    bool matched = read_total == expected &&
                   memcmp(answered, plan->fields[FIELD_EXPECTED], expected) == 0;
    free(answered);
    return matched;
}

static bool wait_for_startup(const struct descriptor *plan, long long seconds)
{
    for (long long waited = 0; waited <= seconds; waited += POLL_SECONDS) {
        if (acknowledgement_matches(plan)) {
            return true;
        }
        sleep(POLL_SECONDS);
    }
    return false;
}

/* ---------------------------------------------------------------- apply --- */

static int roll_back(const struct descriptor *plan, const char *detail)
{
    stop_processes_under(plan->fields[FIELD_INSTALL]);

    if (directory_present(plan->fields[FIELD_INSTALL]) &&
        !move_directory(plan->fields[FIELD_INSTALL], plan->fields[FIELD_REJECTED])) {
        write_result(plan, RESULT_RECOVERY, "the new installation could not be moved aside");
        return EXIT_FAILED;
    }
    if (!directory_present(plan->fields[FIELD_INSTALL]) &&
        directory_present(plan->fields[FIELD_BACKUP]) &&
        !move_directory(plan->fields[FIELD_BACKUP], plan->fields[FIELD_INSTALL])) {
        write_result(plan, RESULT_RECOVERY, "the previous installation could not be put back");
        return EXIT_FAILED;
    }

    write_result(plan, RESULT_RESTORED, detail);
    launch_restored(plan);
    return EXIT_FAILED;
}

static int apply_update(const struct descriptor *plan)
{
    long long parent = field_number(plan, FIELD_PARENT_PID);
    long long exit_timeout = field_number(plan, FIELD_EXIT_TIMEOUT);
    long long ready_timeout = field_number(plan, FIELD_READY_TIMEOUT);
    if (exit_timeout < 0 || ready_timeout < 0) {
        note("the update descriptor has no usable timeouts", NULL);
        return EXIT_UNUSABLE;
    }

    if (!wait_for_exit(plan->fields[FIELD_INSTALL], (pid_t)parent, exit_timeout)) {
        write_result(plan, RESULT_ABANDONED, "Hanly did not close, so nothing was changed");
        return EXIT_FAILED;
    }

    /* Rechecked here, not only when the plan was made: between deciding and
     * mutating, the only thing that has not changed is the plan. */
    if (!identity_matches(plan->fields[FIELD_INSTALL], field_number(plan, FIELD_INSTALL_DEVICE),
                          field_number(plan, FIELD_INSTALL_INODE)) ||
        !identity_matches(plan->fields[FIELD_CANDIDATE],
                          field_number(plan, FIELD_CANDIDATE_DEVICE),
                          field_number(plan, FIELD_CANDIDATE_INODE))) {
        write_result(plan, RESULT_ABANDONED,
                     "the installation changed while the update was waiting");
        return EXIT_FAILED;
    }

    if (!move_directory(plan->fields[FIELD_INSTALL], plan->fields[FIELD_BACKUP])) {
        write_result(plan, RESULT_ABANDONED, "the installation could not be moved aside");
        return EXIT_FAILED;
    }
    if (!move_directory(plan->fields[FIELD_CANDIDATE], plan->fields[FIELD_INSTALL])) {
        return roll_back(plan, "the new version could not be installed");
    }

    unlink(plan->fields[FIELD_ACK]);
    if (!launch_candidate(plan)) {
        return roll_back(plan, "the new version could not be started");
    }
    if (!wait_for_startup(plan, ready_timeout)) {
        return roll_back(plan, "the new version did not start, so the previous one is back");
    }

    write_result(plan, RESULT_COMMITTED, "the new version started");
    return EXIT_OK;
}

/* -------------------------------------------------------------- recover --- */

/*
 * Reached only after a helper died part way through. The filesystem is the
 * authority: what is actually there decides what to do, because a record
 * written before a crash may describe an intention that never happened.
 *
 * An interrupted, uncommitted exchange rolls back rather than retrying a
 * candidate nobody watched start.
 */
static int recover_update(const struct descriptor *plan)
{
    bool installed = directory_present(plan->fields[FIELD_INSTALL]);
    bool backed_up = directory_present(plan->fields[FIELD_BACKUP]);
    bool candidate = directory_present(plan->fields[FIELD_CANDIDATE]);

    if (installed && !backed_up) {
        write_result(plan, RESULT_ABANDONED, "the update never started; nothing was changed");
        return EXIT_FAILED;
    }
    if (!installed && backed_up) {
        if (!move_directory(plan->fields[FIELD_BACKUP], plan->fields[FIELD_INSTALL])) {
            write_result(plan, RESULT_RECOVERY,
                         "the previous installation is still beside the installation path");
            return EXIT_FAILED;
        }
        write_result(plan, RESULT_RESTORED, "an interrupted update was undone");
        launch_restored(plan);
        return EXIT_FAILED;
    }
    if (installed && backed_up) {
        /* The candidate may have acknowledged successfully just before this
         * helper died while persisting the result.  Its exact inode and exact
         * transaction-bound answer are enough to retain it; rolling it back
         * here would turn a diagnostic-write failure into a product rollback. */
        if (identity_matches(plan->fields[FIELD_INSTALL],
                             field_number(plan, FIELD_CANDIDATE_DEVICE),
                             field_number(plan, FIELD_CANDIDATE_INODE)) &&
            acknowledgement_matches(plan)) {
            write_result(plan, RESULT_COMMITTED, "the new version started");
            return EXIT_OK;
        }
        return roll_back(plan, "an interrupted update was undone");
    }

    write_result(plan, RESULT_RECOVERY,
                 candidate ? "the installation is missing and a candidate is staged"
                           : "the installation is missing and nothing can replace it");
    return EXIT_FAILED;
}

/* ----------------------------------------------------------------- main --- */

static void usage(void)
{
    fprintf(stderr, "usage: %s [--recover] <descriptor>\n", program_name);
}

int main(int argc, char **argv)
{
    if (argc >= 1 && argv[0] != NULL && argv[0][0] != '\0') {
        program_name = argv[0];
    }

    bool recover = false;
    const char *path = NULL;
    for (int index = 1; index < argc; index++) {
        if (strcmp(argv[index], "--recover") == 0) {
            recover = true;
        } else if (path == NULL) {
            path = argv[index];
        } else {
            usage();
            return EXIT_UNUSABLE;
        }
    }
    if (path == NULL) {
        usage();
        return EXIT_UNUSABLE;
    }

    struct descriptor plan;
    if (!descriptor_read(path, &plan)) {
        return EXIT_UNUSABLE;
    }

    int lock = claim_lock(plan.fields[FIELD_LOCK]);
    if (lock < 0) {
        descriptor_free(&plan);
        return EXIT_UNUSABLE;
    }

    int status = recover ? recover_update(&plan) : apply_update(&plan);

    flock(lock, LOCK_UN);
    close(lock);
    descriptor_free(&plan);
    return status;
}
