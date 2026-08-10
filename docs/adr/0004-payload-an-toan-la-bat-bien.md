# ADR 0004 — "Payload an toàn" là bất biến có test, không phải lời hứa

- **Ngày:** 2026-08-10
- **Trạng thái:** Accepted
- **Liên quan:** `src/safe_probe/payloads.py`, `tests/test_payloads.py`

## Bối cảnh

Đề bài liệt kê payload được phép (chuỗi dài, ký tự đặc biệt, giá trị rỗng, sai
kiểu) và payload bị cấm (phá hoại, truy cập hệ thống, thay đổi dữ liệu thật).

Cách làm mặc định là viết một danh sách payload rồi ghi trong README rằng chúng
an toàn. Vấn đề: danh sách đó sẽ được sửa. Người sau thêm một chuỗi "để thử xem
sao", README không đổi, và tài liệu bắt đầu nói dối.

## Quyết định

Định nghĩa cái bị cấm bằng regex, rồi bắt test quét ngược catalogue.

```python
FORBIDDEN_PATTERNS = {
    "sql-injection":     r"('\s*(or|and)\s|--\s|\bunion\s+select\b|;\s*drop\b)",
    "xss":               r"(<\s*script|javascript:|onerror\s*=|<\s*iframe)",
    "path-traversal":    r"(\.\./|\.\.\\|%2e%2e)",
    "command-injection": r"(;\s*(rm|cat|curl|wget|nc|sh|bash)\b|\$\(|`[^`]+`)",
    ...  # 11 lớp
}
```

Ba khẳng định được test, và cả ba đều cần:

1. **Mọi payload trong catalogue đều vượt qua toàn bộ pattern.** Thêm một chuỗi
   SQLi vào `SAFE_PAYLOADS` là làm đỏ test suite — trước khi nó đến gần socket.
2. **Mỗi pattern bắt được ít nhất một chuỗi tấn công thật** (`KNOWN_BAD`). Một
   regex không bao giờ khớp gì thì vẫn làm test (1) xanh mà không bảo vệ gì cả.
   Đây là kiểm soát quan trọng nhất và cũng là thứ dễ quên nhất.
3. **`check_safe` chạy lại tại thời điểm dùng**, không chỉ khi viết catalogue —
   `payloads.get()` gọi nó, và `plan.py` gọi lại lần nữa trước khi gửi.

## Hai lỗi mà chính test này tìm ra

Không phải giả định — cả hai xảy ra khi viết repo:

**`as_text` dùng `repr()` nên bỏ lọt ký tự điều khiển.** `repr("a\r\nSet-Cookie: x")`
trả về chuỗi chứa hai ký tự `\` và `r`, không phải CR thật, nên pattern
`[\r\n]` không khớp. Sửa: `as_text` ghép cả giá trị thô lẫn `repr` — thô để bắt
ký tự điều khiển thật, `repr` để bắt payload viết escape ra chữ.

**`\$ne\s*:` không khớp `{"$ne": null}`** vì giữa `$ne` và `:` có dấu nháy kép.
Sửa thành `\$(where|ne|gt|lt|regex|in|exists)\b`.

Cả hai đều là lỗi mà đọc code không thấy. Đó chính là lý do khẳng định (2) tồn tại.

## Ranh giới "không thay đổi dữ liệu thật"

Payload an toàn chưa đủ — gửi payload hoàn toàn vô hại tới `POST /api/Feedbacks`
vẫn tạo ra bản ghi thật. Nên ràng buộc thứ hai nằm ở allowlist, không ở catalogue:

- `policy.yml` chỉ mở endpoint đọc, cộng `POST /rest/user/login` (sai credential →
  401, không ghi gì) và `POST /echo` của lab-app (phản chiếu, không lưu).
- `tests/test_policy.py::test_no_route_can_write_real_data` khẳng định mọi route
  có method khác GET/HEAD đều nằm trong danh sách hai cái đó.
- `suite.INJECTION_POINTS` được viết tay. Đoán chỗ nhét payload là cách một công
  cụ "an toàn" vô tình POST vào một endpoint có ghi.

## Cái giá phải trả

- **Regex có false positive.** Một payload hợp lệ chứa `${` sẽ bị `template-injection`
  chặn. Chấp nhận: từ chối nhầm một payload rẻ hơn nhiều so với gửi nhầm một payload.
- **Danh sách pattern không đầy đủ.** 11 lớp không phải là tất cả các loại tấn
  công. Nó không cần đầy đủ — nó cần bắt được thứ vô tình lọt vào một catalogue
  payload an toàn, và mục đích đó thì 11 lớp đủ.
