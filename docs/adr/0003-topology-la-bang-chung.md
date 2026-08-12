# ADR 0003 — Target không publish port: topology là bằng chứng

- **Ngày:** 2026-08-10
- **Trạng thái:** Accepted
- **Liên quan:** `docker-compose.yml`, `scripts/up.sh`, `scripts/smoke.sh`

## Bối cảnh

Sản phẩm bàn giao có một dòng: **"Request đều đi qua API Gateway."**

Câu này rất dễ *nói* và rất khó *chứng minh*. Cách hay gặp là:

- Đặt `GATEWAY_URL` trong config của tool → chứng minh tool được *cấu hình* để đi
  qua gateway, không chứng minh nó *phải* đi qua.
- Thêm check trong code tool (`_build_url` của tuần 3) → chứng minh code hiện tại
  làm đúng, không chứng minh gì về code sau khi bị sửa, bị inject, hay chạy nhầm.
- Grep code xem có `localhost:3000` không → chứng minh tại thời điểm grep.

Cả ba đều là bằng chứng về *ý định của tool*. Nhưng tool chính là thứ đang bị
kiểm thử, nên ý định của nó không phải là bằng chứng.

## Quyết định

Target không có `ports:`. Chúng nằm trên một network khai báo `internal: true`.
Chỉ gateway publish `8000`.

```yaml
services:
  gateway:
    ports: ["8000:8000"]      # cánh cửa duy nhất
    networks: [edge, internal]
  lab-app:
    networks: [internal]      # không có ports
  juice-shop:
    networks: [internal]      # tuần 3 publish 3000 ở đây; tuần 4 thì không

networks:
  edge:
  internal:
    internal: true            # Docker không tạo route nào ra ngoài
```

Hệ quả: **trên host không tồn tại địa chỉ nào dẫn tới juice-shop hay lab-app.**

```
$ curl --max-time 2 http://localhost:3000/
curl: (7) Failed to connect to localhost port 3000: Connection refused
```

Đây không còn là một quy ước lập trình mà là một tính chất của môi trường. Nó
đúng kể cả khi:

- `safe_probe/client.py` bị sửa để trỏ thẳng vào target,
- có người chạy `curl` bằng tay,
- lớp LLM bị prompt-injection và "quyết định" bỏ qua gateway.

Không cái nào trong ba trường hợp đó có gì để kết nối tới.

## Vì sao điều này đáng giá hơn cả việc chọn Kong hay không

ADR 0001 nói gateway tự viết vẫn giữ được tính chất "ngoài tiến trình". ADR này
là lý do câu đó đúng: tính chất đó đến từ **topology**, không đến từ việc gateway
được viết bằng gì. Một Kong với `ports: ["3000:3000"]` trên juice-shop sẽ yếu hơn
gateway tự viết ở đây.

## Cái giá phải trả

- **Debug target khó hơn.** Không xem trực tiếp được Juice Shop bằng trình duyệt.
  Muốn xem: `docker compose exec juice-shop ...`, hoặc tạm thêm port và **nhớ bỏ
  đi** — AGENTS.md ghi rõ đây là việc tuyệt đối không làm khi commit.
- **Healthcheck phải chạy bên trong container.** Không `curl` từ host được nữa;
  compose dùng `node -e` cho juice-shop và `python -c` cho hai service kia (image
  juice-shop không có sẵn `curl` lẫn `wget`).
- **Không dùng lại được `scripts/` của tuần 3.** Chúng đều giả định
  `localhost:3000`. Đúng như mong muốn.

## Hệ quả

- `scripts/up.sh` kết thúc bằng việc *tự kiểm tra* điều này và **exit 1** nếu
  `localhost:3000` hoặc `localhost:8080` trả lời. Một regression ở đây làm hỏng
  luận điểm chính của repo, nên nó phải làm hỏng cả script.
- `scripts/smoke.sh` ghi lại bằng chứng vào
  `reports/evidence/juice-shop-01-no-direct-access.txt` và
  `reports/evidence/lab-app-01-no-direct-access.txt`, kèm output `docker inspect`
  cho thấy `NetworkSettings.Ports` rỗng.
