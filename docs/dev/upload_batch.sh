args=()
while IFS= read -r f; do
  args+=(-F "files=@$f")
done < <(find ./docs -type f | sort)

curl -X POST \
"http://192.168.0.181:8000/api/kb/kb-01/docs/upload/batch" \
"${args[@]}" | python3 -m json.tool 2>/dev/null