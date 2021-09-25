#!/bin/sh
SRC=/home/
DEST=/storage/shared/backup/jet/home/
rsync -x -rlogtD --delete-after -q "${SRC}" "${DEST}"

