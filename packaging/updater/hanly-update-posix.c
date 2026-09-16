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
#define MAX_TIMEOUT_SECONDS (24 * 60 * 60)

struct descriptor {
    char *fields[FIELD_COUNT];
    size_t lengths[FIELD_COUNT];
};

enum move_status {
    MOVE_FAILED = 0,
    MOVE_DURABLE,
    MOVE_UNCERTAIN
};

enum process_match {
    PROCESS_DIFFERENT = 0,
    PROCESS_MATCHES,
    PROCESS_UNKNOWN
};

struct process_identity {
    pid_t pid;
    uint64_t started;
};

static const char *program_name = "hanly-update-posix";

#ifdef HANLY_UPDATER_TEST_HOOKS
static bool fail_test_call(const char *name, unsigned int *calls)
{
    const char *configured = getenv(name);
    (*calls)++;
    if (configured == NULL || configured[0] == '\0') {
        return false;
    }

    errno = 0;
    char *end = NULL;
    unsigned long requested = strtoul(configured, &end, 10);
    return errno == 0 && end != configured && *end == '\0' && requested == *calls;
}
#endif

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
static bool flush_handle(int handle, bool strongest)
{
#if defined(__APPLE__) && defined(F_FULLFSYNC)
    if (strongest) {
        return fcntl(handle, F_FULLFSYNC) == 0;
    }
#else
    (void)strongest;
#endif
    return fsync(handle) == 0;
}

static bool sync_directory(const char *path)
{
#ifdef HANLY_UPDATER_TEST_HOOKS
    static unsigned int calls = 0;
    if (fail_test_call("HANLY_TEST_FAIL_DIRECTORY_SYNC_AT", &calls)) {
        errno = EIO;
        return false;
    }
#endif

    int handle = open(path, O_RDONLY | O_CLOEXEC
#ifdef O_DIRECTORY
                                | O_DIRECTORY
#endif
    );
    if (handle < 0) {
        return false;
    }
    bool flushed = flush_handle(handle, false);
    bool closed = close(handle) == 0;
    return flushed && closed;
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

static enum move_status move_directory(const char *from, const char *to)
{
    if (rename(from, to) != 0) {
        note("could not move a directory into place", from);
        return MOVE_FAILED;
    }

    char from_parent[PATH_MAX];
    char to_parent[PATH_MAX];
    if (!parent_of(from, from_parent, sizeof(from_parent)) ||
        !parent_of(to, to_parent, sizeof(to_parent))) {
        return MOVE_UNCERTAIN;
    }
    bool from_flushed = sync_directory(from_parent);
    bool to_flushed = strcmp(from_parent, to_parent) == 0 || sync_directory(to_parent);
    return from_flushed && to_flushed ? MOVE_DURABLE : MOVE_UNCERTAIN;
}

static bool write_all(int handle, const char *data, size_t size)
{
    size_t written_total = 0;
    while (written_total < size) {
        ssize_t written = write(handle, data + written_total, size - written_total);
        if (written < 0 && errno == EINTR) {
            continue;
        }
        if (written <= 0) {
            return false;
        }
        written_total += (size_t)written;
    }
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
    const char *message = detail != NULL ? detail : "";
    bool written_ok = write_all(handle, outcome, strlen(outcome)) && write_all(handle, "\n", 1) &&
                      write_all(handle, message, strlen(message)) && write_all(handle, "\n", 1);
#ifdef HANLY_UPDATER_TEST_HOOKS
    if (getenv("HANLY_TEST_FAIL_RESULT_WRITE") != NULL) {
        written_ok = false;
        errno = EIO;
    }
#endif
    bool flushed = written_ok && flush_handle(handle, true);
    bool closed = close(handle) == 0;

    if (!flushed || !closed || rename(temporary, plan->fields[FIELD_RESULT]) != 0) {
        unlink(temporary);
        return false;
    }
    return sync_parent(plan->fields[FIELD_RESULT]);
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

/* The shorter of the two kernels' limits on the name they report for a
 * process: Linux keeps 15 characters, macOS 16. */
#define REPORTED_NAME_LIMIT 15

/* The descriptor names the executable relative to the installation root; a
 * kernel reports only its last component. */
static const char *executable_name(const char *executable)
{
    const char *separator = strrchr(executable, '/');
    return separator != NULL ? separator + 1 : executable;
}

/* A process running out of the installation is running the installation's own
 * executable, so a name that is not that one rules the process out without the
 * program path the kernel is withholding. A name at the reported limit has
 * been truncated and stands for everything it could have been. */
static bool name_could_be(const char *name, const char *executable)
{
    size_t length = strlen(name);
    if (length == 0) {
        return true;
    }
    if (strncmp(name, executable, length) != 0) {
        return false;
    }
    return executable[length] == '\0' || length >= REPORTED_NAME_LIMIT;
}

#if defined(__APPLE__)
/* By the program each process is actually running, never by its name: the
 * shell, the Control Center and the lookup child all run this installation's
 * executable, and anything else called hanly-desktop is none of our business. */
static bool process_details(pid_t pid, char *program, size_t size, uint64_t *started)
{
    struct proc_bsdinfo info;
    if (proc_pidpath(pid, program, (uint32_t)size) <= 0 ||
        proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &info, sizeof(info)) != (int)sizeof(info)) {
        return false;
    }
    *started = (uint64_t)info.pbi_start_tvsec * 1000000u + (uint64_t)info.pbi_start_tvusec;
    return true;
}

static bool inspection_failure_may_hide(pid_t pid, const char *executable)
{
    struct proc_bsdinfo info;
    if (proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &info, sizeof(info)) != (int)sizeof(info)) {
        return kill(pid, 0) == 0;
    }
    if (info.pbi_uid != geteuid()) {
        return false;
    }
    const char *reported = info.pbi_name[0] != '\0' ? info.pbi_name : info.pbi_comm;
    return name_could_be(reported, executable_name(executable));
}

static int processes_under(const char *root, const char *executable,
                           struct process_identity *found, int limit)
{
#ifdef HANLY_UPDATER_TEST_HOOKS
    static unsigned int calls = 0;
    if (fail_test_call("HANLY_TEST_FAIL_PROCESS_INSPECTION_AT", &calls)) {
        errno = EIO;
        return -1;
    }
#endif

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
        uint64_t started = 0;
        if (!process_details(pids[index], program, sizeof(program), &started)) {
            if (inspection_failure_may_hide(pids[index], executable)) {
                char identity[32];
                snprintf(identity, sizeof(identity), "%ld", (long)pids[index]);
                note("a running process could not be identified", identity);
                free(pids);
                return -1;
            }
            continue;
        }
        if (path_inside(program, root)) {
            found[count].pid = pids[index];
            found[count].started = started;
            count++;
        }
    }
    free(pids);
    return count;
}
#else
/* Readable for every process on the system, including the ones whose ``exe``
 * link is not: it is where both the name and the start time come from. */
static bool read_process_stat(pid_t pid, char *data, size_t size)
{
    char path[64];
    int written = snprintf(path, sizeof(path), "/proc/%ld/stat", (long)pid);
    if (written < 0 || (size_t)written >= sizeof(path)) {
        errno = EINVAL;
        return false;
    }

    int handle = open(path, O_RDONLY | O_CLOEXEC);
    if (handle < 0) {
        return false;
    }
    ssize_t length;
    do {
        length = read(handle, data, size - 1);
    } while (length < 0 && errno == EINTR);
    int saved = errno;
    close(handle);
    errno = saved;
    if (length <= 0 || (size_t)length >= size - 1) {
        return false;
    }
    data[length] = '\0';
    return true;
}

/* The name sits between the first parenthesis and the last, unescaped: a
 * program is free to have parentheses of its own in it. */
static bool linux_process_name(pid_t pid, char *name, size_t size)
{
    char data[4096];
    if (!read_process_stat(pid, data, sizeof(data))) {
        return false;
    }

    const char *opened = strchr(data, '(');
    const char *closed = strrchr(data, ')');
    if (opened == NULL || closed == NULL || closed <= opened) {
        errno = EINVAL;
        return false;
    }
    size_t length = (size_t)(closed - opened - 1);
    if (length >= size) {
        errno = ENAMETOOLONG;
        return false;
    }
    memcpy(name, opened + 1, length);
    name[length] = '\0';
    return true;
}

static bool linux_process_start(pid_t pid, uint64_t *started)
{
    char data[4096];
    if (!read_process_stat(pid, data, sizeof(data))) {
        return false;
    }

    char *cursor = strrchr(data, ')');
    if (cursor == NULL || cursor[1] != ' ') {
        errno = EINVAL;
        return false;
    }
    cursor += 2;
    for (int field = 3; field <= 22; field++) {
        while (*cursor == ' ') {
            cursor++;
        }
        if (*cursor == '\0') {
            errno = EINVAL;
            return false;
        }
        char *end = cursor;
        while (*end != '\0' && *end != ' ') {
            end++;
        }
        if (field == 22) {
            char saved_character = *end;
            *end = '\0';
            errno = 0;
            char *number_end = NULL;
            unsigned long long value = strtoull(cursor, &number_end, 10);
            bool valid = errno == 0 && number_end != cursor && *number_end == '\0';
            *end = saved_character;
            if (!valid) {
                errno = EINVAL;
                return false;
            }
            *started = (uint64_t)value;
            return true;
        }
        cursor = end;
    }
    errno = EINVAL;
    return false;
}

static bool process_details(pid_t pid, char *program, size_t size, uint64_t *started)
{
    char link[64];
    int written = snprintf(link, sizeof(link), "/proc/%ld/exe", (long)pid);
    if (written < 0 || (size_t)written >= sizeof(link)) {
        errno = EINVAL;
        return false;
    }
    ssize_t length = readlink(link, program, size - 1);
    if (length <= 0 || (size_t)length >= size - 1) {
        return false;
    }
    program[length] = '\0';
    return linux_process_start(pid, started);
}

static bool inspection_failure_may_hide(pid_t pid, const char *executable)
{
    char path[64];
    int written = snprintf(path, sizeof(path), "/proc/%ld", (long)pid);
    if (written < 0 || (size_t)written >= sizeof(path)) {
        return true;
    }
    struct stat status;
    if (stat(path, &status) != 0 || status.st_uid != geteuid()) {
        return false;
    }

    char name[256];
    return !linux_process_name(pid, name, sizeof(name)) ||
           name_could_be(name, executable_name(executable));
}

static int processes_under(const char *root, const char *executable,
                           struct process_identity *found, int limit)
{
#ifdef HANLY_UPDATER_TEST_HOOKS
    static unsigned int calls = 0;
    if (fail_test_call("HANLY_TEST_FAIL_PROCESS_INSPECTION_AT", &calls)) {
        errno = EIO;
        return -1;
    }
#endif

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
        char program[PATH_MAX];
        uint64_t started = 0;
        if (!process_details((pid_t)value, program, sizeof(program), &started)) {
            if (inspection_failure_may_hide((pid_t)value, executable)) {
                note("a running process could not be identified", entry->d_name);
                closedir(processes);
                return -1;
            }
            continue;
        }
        if (path_inside(program, root)) {
            found[count].pid = (pid_t)value;
            found[count].started = started;
            count++;
        }
    }
    closedir(processes);
    return count;
}
#endif

#define MAX_TRACKED_PROCESSES 256

static void sleep_for_poll(void);

static enum process_match process_still_matches(const char *root,
                                                const struct process_identity *expected)
{
    char program[PATH_MAX];
    uint64_t started = 0;
    if (!process_details(expected->pid, program, sizeof(program), &started)) {
        if (kill(expected->pid, 0) != 0 && errno == ESRCH) {
            return PROCESS_DIFFERENT;
        }
        return PROCESS_UNKNOWN;
    }
    return started == expected->started && path_inside(program, root) ? PROCESS_MATCHES
                                                                      : PROCESS_DIFFERENT;
}

/* The process that asked for this update is answered for by its pid alone: it
 * was alive when the descriptor was written, so a pid reused since belongs to
 * a process that started later and is not it. */
static bool installation_is_free(const char *root, const char *executable, pid_t parent)
{
    if (parent > 0 && kill(parent, 0) == 0) {
        return false;
    }
    struct process_identity found[MAX_TRACKED_PROCESSES];
    int count = processes_under(root, executable, found, MAX_TRACKED_PROCESSES);
    /* Inspection failing is not the same as nothing running. Refusing to act
     * on an unknown answer is the whole point of asking. */
    return count == 0;
}

static bool signal_process(const char *root, const struct process_identity *process, int signal)
{
    enum process_match match = process_still_matches(root, process);
    if (match == PROCESS_UNKNOWN) {
        return false;
    }
    if (match == PROCESS_DIFFERENT) {
        return true;
    }
    return kill(process->pid, signal) == 0 || errno == ESRCH;
}

static bool stop_processes_under(const char *root, const char *executable)
{
    struct process_identity found[MAX_TRACKED_PROCESSES];
    const int signals[] = {SIGTERM, SIGKILL};
    for (size_t attempt = 0; attempt < sizeof(signals) / sizeof(signals[0]); attempt++) {
        int count = processes_under(root, executable, found, MAX_TRACKED_PROCESSES);
        if (count < 0) {
            return false;
        }
        if (count == 0) {
            return true;
        }
        for (int index = 0; index < count; index++) {
            if (!signal_process(root, &found[index], signals[attempt])) {
                return false;
            }
        }
        sleep_for_poll();
    }

    int remaining = processes_under(root, executable, found, MAX_TRACKED_PROCESSES);
    return remaining == 0;
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

static void report_launch_failure(int handle)
{
    int failure = errno != 0 ? errno : EIO;
    (void)write_all(handle, (const char *)&failure, sizeof(failure));
    _exit(EXIT_FAILED);
}

static bool launch_detached(const struct descriptor *plan, bool acknowledging)
{
    char program[PATH_MAX];
    int launch_status[2] = {-1, -1};
    if (pipe(launch_status) != 0 || fcntl(launch_status[1], F_SETFD, FD_CLOEXEC) != 0) {
        if (launch_status[0] >= 0) {
            close(launch_status[0]);
            close(launch_status[1]);
        }
        note("could not create the launch status pipe", NULL);
        return false;
    }

    pid_t child = fork();
    if (child < 0) {
        close(launch_status[0]);
        close(launch_status[1]);
        note("could not start the installation", NULL);
        return false;
    }
    if (child > 0) {
        close(launch_status[1]);
        int status = 0;
        pid_t waited;
        do {
            waited = waitpid(child, &status, 0);
        } while (waited < 0 && errno == EINTR);

        int failure = 0;
        ssize_t received;
        do {
            received = read(launch_status[0], &failure, sizeof(failure));
        } while (received < 0 && errno == EINTR);
        close(launch_status[0]);
        if (waited != child || !WIFEXITED(status) || WEXITSTATUS(status) != EXIT_OK ||
            received != 0) {
            note("could not execute the installation", received == (ssize_t)sizeof(failure)
                                                           ? strerror(failure)
                                                           : NULL);
            return false;
        }
        return true;
    }

    close(launch_status[0]);
    if (setsid() < 0) {
        report_launch_failure(launch_status[1]);
    }
    pid_t application = fork();
    if (application < 0) {
        report_launch_failure(launch_status[1]);
    }
    if (application > 0) {
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
    report_launch_failure(launch_status[1]);
    return false;
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

static bool deadline_after(long long seconds, struct timespec *deadline)
{
    if (seconds < 0 || seconds > MAX_TIMEOUT_SECONDS ||
        clock_gettime(CLOCK_MONOTONIC, deadline) != 0) {
        return false;
    }
    deadline->tv_sec += (time_t)seconds;
    return true;
}

static bool deadline_reached(const struct timespec *deadline)
{
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) {
        return true;
    }
    return now.tv_sec > deadline->tv_sec ||
           (now.tv_sec == deadline->tv_sec && now.tv_nsec >= deadline->tv_nsec);
}

static void sleep_for_poll(void)
{
    struct timespec remaining = {.tv_sec = POLL_SECONDS, .tv_nsec = 0};
    while (nanosleep(&remaining, &remaining) != 0 && errno == EINTR) {
    }
}

static bool wait_for_exit(const char *root, const char *executable, pid_t parent,
                          long long seconds)
{
    struct timespec deadline;
    if (!deadline_after(seconds, &deadline)) {
        return false;
    }
    for (;;) {
        if (installation_is_free(root, executable, parent)) {
            return true;
        }
        if (deadline_reached(&deadline)) {
            return false;
        }
        sleep_for_poll();
    }
}

static bool wait_for_startup(const struct descriptor *plan, long long seconds)
{
    struct timespec deadline;
    if (!deadline_after(seconds, &deadline)) {
        return false;
    }
    for (;;) {
        if (acknowledgement_matches(plan)) {
            return true;
        }
        if (deadline_reached(&deadline)) {
            return false;
        }
        sleep_for_poll();
    }
}

/* ---------------------------------------------------------------- apply --- */

static int record_failed_outcome(const struct descriptor *plan, const char *outcome,
                                 const char *detail)
{
    if (!write_result(plan, outcome, detail)) {
        note("could not persist the update result", detail);
    }
    return EXIT_FAILED;
}

static int record_recovery_required(const struct descriptor *plan, const char *detail)
{
    return record_failed_outcome(plan, RESULT_RECOVERY, detail);
}

/* The previous installation is back and durable by the time this runs, so a
 * result file that cannot be written is reported and started anyway: it is a
 * diagnostic, and withholding the build over it would be the larger failure. */
static int record_restored(const struct descriptor *plan, const char *detail)
{
    if (!write_result(plan, RESULT_RESTORED, detail)) {
        note("could not persist the restored result", detail);
    }
    launch_restored(plan);
    return EXIT_FAILED;
}

static bool original_backup_matches(const struct descriptor *plan)
{
    return identity_matches(plan->fields[FIELD_BACKUP],
                            field_number(plan, FIELD_INSTALL_DEVICE),
                            field_number(plan, FIELD_INSTALL_INODE));
}

static bool installed_candidate_matches(const struct descriptor *plan)
{
    return identity_matches(plan->fields[FIELD_INSTALL],
                            field_number(plan, FIELD_CANDIDATE_DEVICE),
                            field_number(plan, FIELD_CANDIDATE_INODE));
}

static bool installed_original_matches(const struct descriptor *plan)
{
    return identity_matches(plan->fields[FIELD_INSTALL],
                            field_number(plan, FIELD_INSTALL_DEVICE),
                            field_number(plan, FIELD_INSTALL_INODE));
}

static int roll_back(const struct descriptor *plan, const char *detail)
{
    bool installed = directory_present(plan->fields[FIELD_INSTALL]);
    if (!original_backup_matches(plan) || (installed && !installed_candidate_matches(plan))) {
        return record_recovery_required(
            plan, "rollback stopped because the installation identities did not match");
    }

#ifdef HANLY_UPDATER_TEST_HOOKS
    if (getenv("HANLY_TEST_REFUSE_PROCESS_STOP") != NULL) {
        return record_recovery_required(plan, "the new installation could not be proved stopped");
    }
#endif
    if (installed && !stop_processes_under(plan->fields[FIELD_INSTALL],
                                           plan->fields[FIELD_EXECUTABLE])) {
        return record_recovery_required(plan, "the new installation could not be proved stopped");
    }
    if ((directory_present(plan->fields[FIELD_INSTALL]) && !installed_candidate_matches(plan)) ||
        !original_backup_matches(plan)) {
        return record_recovery_required(
            plan, "rollback stopped because the installation identities changed");
    }

    if (directory_present(plan->fields[FIELD_INSTALL])) {
        enum move_status rejected =
            move_directory(plan->fields[FIELD_INSTALL], plan->fields[FIELD_REJECTED]);
        if (rejected == MOVE_FAILED) {
            return record_recovery_required(plan, "the new installation could not be moved aside");
        }
        if (rejected == MOVE_UNCERTAIN) {
            return record_recovery_required(
                plan, "the new installation moved aside but its durability is uncertain");
        }
    }
    if (!directory_present(plan->fields[FIELD_INSTALL])) {
        enum move_status restored =
            move_directory(plan->fields[FIELD_BACKUP], plan->fields[FIELD_INSTALL]);
        if (restored == MOVE_FAILED) {
            return record_recovery_required(plan,
                                            "the previous installation could not be put back");
        }
        if (restored == MOVE_UNCERTAIN) {
            return record_recovery_required(
                plan, "the previous installation returned but its durability is uncertain");
        }
    }

    return record_restored(plan, detail);
}

static int apply_update(const struct descriptor *plan)
{
    long long parent = field_number(plan, FIELD_PARENT_PID);
    long long exit_timeout = field_number(plan, FIELD_EXIT_TIMEOUT);
    long long ready_timeout = field_number(plan, FIELD_READY_TIMEOUT);
    if (parent < 0 || exit_timeout < 0 || exit_timeout > MAX_TIMEOUT_SECONDS ||
        ready_timeout < 0 || ready_timeout > MAX_TIMEOUT_SECONDS) {
        note("the update descriptor has no usable timeouts", NULL);
        return EXIT_UNUSABLE;
    }

    if (!wait_for_exit(plan->fields[FIELD_INSTALL], plan->fields[FIELD_EXECUTABLE],
                       (pid_t)parent, exit_timeout)) {
        return record_failed_outcome(plan, RESULT_ABANDONED,
                                     "Hanly did not close, so nothing was changed");
    }

    /* Rechecked here, not only when the plan was made: between deciding and
     * mutating, the only thing that has not changed is the plan. */
    if (!identity_matches(plan->fields[FIELD_INSTALL], field_number(plan, FIELD_INSTALL_DEVICE),
                          field_number(plan, FIELD_INSTALL_INODE)) ||
        !identity_matches(plan->fields[FIELD_CANDIDATE],
                          field_number(plan, FIELD_CANDIDATE_DEVICE),
                          field_number(plan, FIELD_CANDIDATE_INODE))) {
        return record_failed_outcome(
            plan, RESULT_ABANDONED, "the installation changed while the update was waiting");
    }

    enum move_status backed_up =
        move_directory(plan->fields[FIELD_INSTALL], plan->fields[FIELD_BACKUP]);
    if (backed_up == MOVE_FAILED) {
        return record_failed_outcome(plan, RESULT_ABANDONED,
                                     "the installation could not be moved aside");
    }
    if (backed_up == MOVE_UNCERTAIN) {
        return record_recovery_required(
            plan, "the installation moved aside but its durability is uncertain");
    }

    enum move_status installed =
        move_directory(plan->fields[FIELD_CANDIDATE], plan->fields[FIELD_INSTALL]);
    if (installed == MOVE_FAILED) {
        return roll_back(plan, "the new version could not be installed");
    }
    if (installed == MOVE_UNCERTAIN) {
        return roll_back(plan, "the new version was not durably installed");
    }

    if (unlink(plan->fields[FIELD_ACK]) != 0 && errno != ENOENT) {
        return roll_back(plan, "the previous startup acknowledgement could not be removed");
    }
    if (!launch_candidate(plan)) {
        return roll_back(plan, "the new version could not be started");
    }
    if (!wait_for_startup(plan, ready_timeout)) {
        return roll_back(plan, "the new version did not start, so the previous one is back");
    }

    if (!write_result(plan, RESULT_COMMITTED, "the new version started")) {
        note("could not persist the committed result", NULL);
        return EXIT_FAILED;
    }
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
    bool rejected = directory_present(plan->fields[FIELD_REJECTED]);

    if (installed && !backed_up) {
        if (!installed_original_matches(plan)) {
            return record_recovery_required(
                plan, "the only installed tree is not the recorded previous installation");
        }
        if (rejected) {
            if (!sync_parent(plan->fields[FIELD_INSTALL])) {
                return record_recovery_required(
                    plan, "the restored installation could not be made durable");
            }
            return record_restored(plan, "an interrupted rollback was completed");
        }
        return record_failed_outcome(plan, RESULT_ABANDONED,
                                     "the update never started; nothing was changed");
    }
    if (!installed && backed_up) {
        if (!original_backup_matches(plan)) {
            return record_recovery_required(
                plan, "the previous installation does not have its recorded identity");
        }
        enum move_status restored =
            move_directory(plan->fields[FIELD_BACKUP], plan->fields[FIELD_INSTALL]);
        if (restored == MOVE_FAILED) {
            return record_recovery_required(
                plan, "the previous installation is still beside the installation path");
        }
        if (restored == MOVE_UNCERTAIN) {
            return record_recovery_required(
                plan, "the previous installation returned but its durability is uncertain");
        }
        return record_restored(plan, "an interrupted update was undone");
    }
    if (installed && backed_up) {
        if (!installed_candidate_matches(plan) || !original_backup_matches(plan)) {
            return record_recovery_required(
                plan, "recovery stopped because the installation identities did not match");
        }
        /* The candidate may have acknowledged successfully just before this
         * helper died while persisting the result.  Its exact inode and exact
         * transaction-bound answer are enough to retain it; rolling it back
         * here would turn a diagnostic-write failure into a product rollback. */
        if (acknowledgement_matches(plan)) {
            if (!write_result(plan, RESULT_COMMITTED, "the new version started")) {
                note("could not persist the committed result", NULL);
                return EXIT_FAILED;
            }
            return EXIT_OK;
        }
        return roll_back(plan, "an interrupted update was undone");
    }

    return record_recovery_required(
        plan, candidate ? "the installation is missing and a candidate is staged"
                        : "the installation is missing and nothing can replace it");
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
