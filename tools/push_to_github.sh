#!/usr/bin/env bash
# 把当前目录推到 GitHub。需要的只是一个带 repo 权限的 token。
#
#   GH_TOKEN=ghp_xxx ./tools/push_to_github.sh                  # 新建 <你的账号>/image-sorter
#   GH_TOKEN=ghp_xxx ./tools/push_to_github.sh my-repo          # 新建指定名字的仓库
#   GH_TOKEN=ghp_xxx ./tools/push_to_github.sh owner/repo       # 推到已有仓库
#
# token 只在命令行里用一次，不写进 .git/config 或 git remote。

set -euo pipefail

TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
if [ -z "$TOKEN" ]; then
    echo "先设置 GH_TOKEN，例如：GH_TOKEN=ghp_xxx $0" >&2
    exit 1
fi

TARGET="${1:-image-sorter}"
API="https://api.github.com"
AUTH=(-H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json")

json_field() {
    python3 -c "import json,sys; print(json.load(sys.stdin).get('$1',''))"
}

# 1) 确认 token 有效，拿到账号名
ME=$(curl -sS "${AUTH[@]}" "$API/user")
LOGIN=$(printf '%s' "$ME" | json_field login)
if [ -z "$LOGIN" ]; then
    echo "token 无效或者没有读账号的权限：" >&2
    printf '%s\n' "$ME" >&2
    exit 1
fi
echo "账号: $LOGIN"

case "$TARGET" in
    */*)
        OWNER="${TARGET%%/*}"
        REPO="${TARGET##*/}"
        ;;
    *)
        OWNER="$LOGIN"
        REPO="$TARGET"
        ;;
esac

# 2) 仓库不存在就建一个
if ! curl -sf "${AUTH[@]}" "$API/repos/$OWNER/$REPO" > /dev/null; then
    echo "新建仓库 $OWNER/$REPO"
    BODY=$(python3 - "$REPO" <<'PY'
import json, sys
print(json.dumps({
    "name": sys.argv[1],
    "description": "按拍摄时间把图片和视频分到月份文件夹，MIT 许可",
    "private": False,
    "has_issues": True,
    "has_wiki": False,
}, ensure_ascii=False))
PY
)
    CREATED=$(curl -sS -X POST "${AUTH[@]}" -d "$BODY" "$API/user/repos")
    if [ -z "$(printf '%s' "$CREATED" | json_field full_name)" ]; then
        echo "建仓库失败：" >&2
        printf '%s\n' "$CREATED" >&2
        exit 1
    fi
fi

# 3) 本地仓库
if [ ! -d .git ]; then
    git init -q
fi
git config user.name "内战狂热爱好者"
git config user.email "${LOGIN}@users.noreply.github.com"
git add -A
if ! git diff --cached --quiet; then
    git commit -q -m "图片整理 ImageSorter 1.0.0

按拍摄时间把图片和视频分到月份文件夹。
支持 25 种能读出拍摄时间的格式，7 种靠文件名或文件时间兜底。
默认按拍摄时间命名，内容重复的只留最早一张。
MIT 许可。

按月份归档、硬链接整理、重复检测参考 phockup（MIT）。"
fi

# 4) 推送（token 只出现在这条命令里，不落地）
git branch -M main
REMOTE="https://x-access-token:${TOKEN}@github.com/${OWNER}/${REPO}.git"
git push "$REMOTE" main --tags

echo
echo "完成: https://github.com/${OWNER}/${REPO}"
