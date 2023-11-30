#!/bin/bash
declare -a excludes=(
  */.cache/go-build
  */.cache/gopls
  */.cache/mozilla
  */.cache/duplicity
  */.config/discord
  */.local/share/Steam
  */.mozilla
  */Downloads/
  */go/
  */src/github.com/grpc
  */src/github.com/protobuf
  */src/go/
  */src/zfs/
  */src/wallabag/
  */src/golang/
  opt/dolphin-emu
  */ttl
)

declare -a exclude_fmt=()
for e in "${excludes[@]}" ; do
  exclude_fmt+=("--exclude=/$e")
done

BACKUP_ROOT=/home
BACKUP_DEST=/storage/shared/backup/jet/home
rsync -rlogtD --delete-after -q \
  "${exclude_fmt[@]}" \
  --filter="dir-merge,n- .nobackups" \
  "${BACKUP_ROOT}/" "${BACKUP_DEST}/"

