/*
 * ccpost — post key events straight to a process (by pid) via CGEventPostToPid.
 *
 * Unlike AppleScript `keystroke`, which goes to whatever app is frontmost and so
 * breaks the moment another window (a chat app, a video call, a notification)
 * steals focus mid-sequence, pid-targeted posting is delivered to the target
 * process regardless of what is frontmost.
 *
 * This is a low-level input primitive. cc-wake's Driver only ever calls it
 * with a fixed, sealed key sequence (see driver.py); it is intentionally NOT
 * wired to any user-controllable input.
 *
 *   ccpost <pid> <step>...
 *     text:STR   type STR (ASCII)
 *     key:N      press key code N   (36=Return, 51=Backspace, 53=Escape)
 *     delay:MS   sleep MS milliseconds
 *
 * Build: cc -O2 -framework ApplicationServices -o ccpost ccpost.c
 * Requires the calling terminal to have Accessibility permission.
 */
#include <ApplicationServices/ApplicationServices.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static void post_key(pid_t pid, CGKeyCode code) {
    CGEventRef d = CGEventCreateKeyboardEvent(NULL, code, true);
    CGEventRef u = CGEventCreateKeyboardEvent(NULL, code, false);
    CGEventPostToPid(pid, d);
    usleep(10000);
    CGEventPostToPid(pid, u);
    CFRelease(d);
    CFRelease(u);
    usleep(15000);
}

static void post_char(pid_t pid, UniChar ch) {
    CGEventRef d = CGEventCreateKeyboardEvent(NULL, 0, true);
    CGEventRef u = CGEventCreateKeyboardEvent(NULL, 0, false);
    CGEventKeyboardSetUnicodeString(d, 1, &ch);
    CGEventKeyboardSetUnicodeString(u, 1, &ch);
    CGEventPostToPid(pid, d);
    usleep(8000);
    CGEventPostToPid(pid, u);
    CFRelease(d);
    CFRelease(u);
    usleep(25000);
}

int main(int argc, char **argv) {
    if (argc < 3) return 2;
    pid_t pid = (pid_t)atoi(argv[1]);
    for (int i = 2; i < argc; i++) {
        char *a = argv[i];
        if (!strncmp(a, "text:", 5)) {
            for (const char *p = a + 5; *p; p++)
                post_char(pid, (UniChar)(unsigned char)*p);
        } else if (!strncmp(a, "key:", 4)) {
            post_key(pid, (CGKeyCode)atoi(a + 4));
        } else if (!strncmp(a, "delay:", 6)) {
            usleep(atoi(a + 6) * 1000);
        }
    }
    return 0;
}
