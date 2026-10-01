/* Minimal V4L2 control tool (instead of v4l2-ctl from v4l-utils).
 *
 * Usage:
 *   v4l2ctl list [device]
 *   v4l2ctl get  <id> [device]
 *   v4l2ctl set  <id> <value> [device]
 *
 * The id can be given in decimal or hexadecimal (0x...).
 */
#include <errno.h>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#define CTRL_FLAG_NEXT_CTRL 0x80000000U

static void usage(const char *p)
{
	fprintf(stderr,
		"usage:\n"
		"  %s list [dev]\n"
		"  %s get <id> [dev]\n"
		"  %s set <id> <value> [dev]\n", p, p, p);
	exit(2);
}

static unsigned long parse_id(const char *s)
{
	return strtoul(s, NULL, 0);
}

static int do_get(int fd, unsigned id, int quiet)
{
	struct v4l2_ext_control ctl;
	struct v4l2_ext_controls ctrls;

	memset(&ctl, 0, sizeof(ctl));
	memset(&ctrls, 0, sizeof(ctrls));
	ctl.id = id;
	ctrls.which = V4L2_CTRL_WHICH_CUR_VAL;
	ctrls.count = 1;
	ctrls.controls = &ctl;

	if (ioctl(fd, VIDIOC_G_EXT_CTRLS, &ctrls) < 0)
		return -1;
	if (!quiet)
		printf("0x%08x = %d\n", id, ctl.value);
	return ctl.value;
}

static int do_set(int fd, unsigned id, int value)
{
	struct v4l2_ext_control ctl;
	struct v4l2_ext_controls ctrls;

	memset(&ctl, 0, sizeof(ctl));
	memset(&ctrls, 0, sizeof(ctrls));
	ctl.id = id;
	ctl.value = value;
	ctrls.which = V4L2_CTRL_WHICH_CUR_VAL;
	ctrls.count = 1;
	ctrls.controls = &ctl;

	if (ioctl(fd, VIDIOC_S_EXT_CTRLS, &ctrls) < 0) {
		fprintf(stderr, "S_EXT_CTRLS 0x%08x=%d: %s\n", id, value,
			strerror(errno));
		return 1;
	}
	printf("ustawiono 0x%08x = %d\n", id, value);
	return 0;
}

static int do_list(int fd)
{
	struct v4l2_queryctrl qc;
	int n = 0;

	memset(&qc, 0, sizeof(qc));
	qc.id = CTRL_FLAG_NEXT_CTRL;

	while (ioctl(fd, VIDIOC_QUERYCTRL, &qc) == 0) {
		int cur;

		if (qc.flags & V4L2_CTRL_FLAG_DISABLED) {
			qc.id |= CTRL_FLAG_NEXT_CTRL;
			continue;
		}
		if (qc.type == V4L2_CTRL_TYPE_CTRL_CLASS) {
			printf("\n[%s]\n", qc.name);
		} else {
			cur = do_get(fd, qc.id, 1);
			printf("  0x%08x  %-28s min=%-9d max=%-9d step=%-5d "
			       "def=%-6d cur=%d\n",
			       qc.id, qc.name, qc.minimum, qc.maximum, qc.step,
			       qc.default_value, cur);
			n++;
		}
		qc.id |= CTRL_FLAG_NEXT_CTRL;
	}
	printf("\nrazem kontrolek: %d\n", n);
	return 0;
}

int main(int argc, char **argv)
{
	const char *cmd, *dev = "/dev/video0";
	int fd;

	if (argc < 2)
		usage(argv[0]);
	cmd = argv[1];

	if (!strcmp(cmd, "list")) {
		if (argc > 2)
			dev = argv[2];
	} else if (!strcmp(cmd, "get")) {
		if (argc < 3)
			usage(argv[0]);
		if (argc > 3)
			dev = argv[3];
	} else if (!strcmp(cmd, "set")) {
		if (argc < 4)
			usage(argv[0]);
		if (argc > 4)
			dev = argv[4];
	} else {
		usage(argv[0]);
	}

	fd = open(dev, O_RDWR | O_NONBLOCK);
	if (fd < 0) {
		perror(dev);
		return 1;
	}

	if (!strcmp(cmd, "list"))
		do_list(fd);
	else if (!strcmp(cmd, "get"))
		return do_get(fd, parse_id(argv[2]), 0) < 0 ? 1 : 0;
	else
		return do_set(fd, parse_id(argv[2]), atoi(argv[3]));

	close(fd);
	return 0;
}
