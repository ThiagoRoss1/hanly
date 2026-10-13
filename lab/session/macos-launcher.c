/* Lab-only diagnostic launcher; this private SPI is never shipped with Hanly. */
#include <dlfcn.h>
#include <errno.h>
#include <spawn.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

extern char **environ;

int main(int argc, char **argv) {
    int (*disclaim)(posix_spawnattr_t *, bool) =
        dlsym(RTLD_DEFAULT, "responsibility_spawnattrs_setdisclaim");
    if (argc == 2 && strcmp(argv[1], "--lab-probe") == 0) {
        if (disclaim) puts("available");
        return disclaim ? 0 : 77;
    }
    if (argc < 2) return 64;
    if (!disclaim) return 77;

    posix_spawnattr_t attributes;
    int result = posix_spawnattr_init(&attributes);
    if (result) return result;
    result = disclaim(&attributes, true);
    if (!result) result = posix_spawnattr_setflags(&attributes, POSIX_SPAWN_SETEXEC);
    pid_t pid;
    if (!result) result = posix_spawn(&pid, argv[1], NULL, &attributes, argv + 1, environ);
    posix_spawnattr_destroy(&attributes);
    return result ? result : 1;
}
