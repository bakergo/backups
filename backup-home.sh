#!/bin/sh
SRC=/home/
DEST=/storage/shared/backup/jet/home/
rsync -x -a --delete-after --progress "${SRC}" "${DEST}"

