#!/bin/zsh
set -euo pipefail
project_root="${0:A:h}"
cd "$project_root"
architecture="$(uname -m)"
archive="$project_root/启动程序/ZhaolianProfile-0.4.0-macos-$architecture.zip"
target="$project_root/启动程序/macOS-$architecture"
if [[ ! -d "$target/昭濂个人履历库.app" ]]; then
  if [[ ! -f "$archive" ]]; then
    print '请先阅读 docs/Mac迁移指南.md，并取得适合这台 Mac 的启动包。'
    read '?按回车关闭。'
    exit 1
  fi
  mkdir -p "$target"
  /usr/bin/ditto -x -k "$archive" "$target"
fi
open "$target/昭濂个人履历库.app"
