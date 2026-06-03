# Hướng dẫn Deploy VN Stock AI Analyzer

Kiến trúc:
- **Frontend** (React + Vite) → **Vercel** (free)
- **Backend** (FastAPI + vnstock + Gemini) → **Railway** ($5 credit/tháng, persistent, không cold start)
- **Database** (Postgres) → **Neon** (free 0.5 GB)

Chi phí: **$5/tháng** (chỉ Railway, Vercel + Neon free).

> Project cũng tương thích Render (file `render.yaml` sẵn) nếu sau này muốn switch lại free + chấp nhận cold start.

---

## Bước 1 — Push code lên GitHub

```bash
cd "C:/Users/minhn/.gemini/antigravity/scratch/Chứng khoán"
git init
git add .
git commit -m "Initial commit"

# Tạo repo trên github.com (Public hoặc Private đều được)
git remote add origin https://github.com/YOUR_USERNAME/vn-stock-ai.git
git branch -M main
git push -u origin main
```

`.gitignore` đã loại trừ `.venv/`, `node_modules/`, `.env`, `data.db`.

---

## Bước 2 — Tạo Neon Database

1. Vào https://console.neon.tech/signup → đăng ký (GitHub login)
2. Tạo project:
   - **Project name**: `vn-stock-ai`
   - **Region**: `AWS Singapore (ap-southeast-1)` — gần VN nhất
   - **Postgres version**: 16
3. Sau khi tạo, tab **Connection Details**:
   - Role: `neondb_owner`, Database: `neondb`
   - Bật **Pooled connection** (Railway nhiều worker — tránh "too many connections")
   - Copy **Connection string** dạng:
     ```
     postgresql://neondb_owner:abc...@ep-xxx-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
     ```
   - **Lưu lại** — dùng ở bước 3.

Schema tự tạo khi backend start lần đầu (không cần migration thủ công).

---

## Bước 3 — Deploy Backend lên Railway

1. Vào https://railway.com/dashboard
2. **New Project → Deploy from GitHub repo** → chọn `vn-stock-ai`
3. Railway sẽ tạo service mặc định. Vào **Settings** của service:
   - **Root Directory**: `backend`  ← QUAN TRỌNG (vì backend nằm trong subfolder)
   - **Builder**: Nixpacks (auto-detect từ `nixpacks.toml`)
   - **Start Command**: để trống (Railway tự đọc từ `railway.json`)
   - **Healthcheck Path**: `/api/market/status` (đã có sẵn trong railway.json)
4. Vào tab **Variables** và thêm:

   | Key | Value |
   |---|---|
   | `DATABASE_URL` | Pooled connection string từ Neon (bước 2) |
   | `CORS_ORIGINS` | Tạm để trống — sẽ điền ở bước 5 |
   | `GEMINI_MODEL` | `gemini-2.5-flash` (optional) |
   | `GEMINI_API_KEY` | (Optional) Server-side fallback nếu user không nhập qua UI |
   | `PYTHONUTF8` | `1` |

5. Tab **Settings → Networking → Generate Domain** → Railway gán URL dạng:
   ```
   vn-stock-ai-backend-production-xxxx.up.railway.app
   ```
6. Bấm **Deploy** → đợi ~3-5 phút build xong
7. Vào **Deployments → Logs** xem có `Application startup complete` không
8. Test: `https://YOUR_RAILWAY_URL/api/market/status` → trả JSON `{"status": "OPEN/LUNCH/CLOSED", ...}`

> **Lưu ý vnstock**: Railway Singapore region work tốt với vnstock VCI/KBS. Nếu lỡ chọn region khác và bị block, vào Settings → Region → đổi `Asia Southeast (Singapore)`.

---

## Bước 4 — Deploy Frontend lên Vercel

1. Vào https://vercel.com/signup (GitHub login)
2. **Add New... → Project** → Import repo `vn-stock-ai`
3. Cấu hình:
   - **Framework Preset**: Vite (auto-detect)
   - **Root Directory**: `frontend`  ← QUAN TRỌNG
   - **Build Command**: `npm run build` (default)
   - **Output Directory**: `dist` (default)
4. Mở **Environment Variables** thêm:

   | Name | Value | Environment |
   |---|---|---|
   | `VITE_API_BASE` | URL Railway từ bước 3, VD `https://vn-stock-ai-backend-production-xxxx.up.railway.app` (KHÔNG có `/api`, không trailing slash) | Production, Preview, Development |

5. Bấm **Deploy** → ~1-2 phút có URL `https://vn-stock-ai-XXX.vercel.app`

---

## Bước 5 — Update CORS cho backend

Quay lại Railway → Service → **Variables**:

| Key | Value |
|---|---|
| `CORS_ORIGINS` | URL Vercel từ bước 4. VD: `https://vn-stock-ai-xyz.vercel.app` |

Nhiều domain (preview deploy, custom domain) ngăn cách bằng dấu phẩy:
```
https://vn-stock-ai-xyz.vercel.app,https://vn-stock-ai-yourname.vercel.app
```

Railway tự restart sau khi save.

---

## Bước 6 — Test production

1. Mở `https://vn-stock-ai-XXX.vercel.app`
2. Bấm **Cấu hình API Key** → dán Gemini key
3. Chọn mã (VD: FPT) → phải thấy chart, fundamentals (P/E, ROE...), news load
4. Bấm **Phân tích AI** → trả về khuyến nghị có cấu trúc
5. Mua thử 100 CP → reload trang → vẫn thấy holdings (đã persist vào Neon Postgres)
6. Bấm **Backtest → Quét VN30** → chạy thử trên cloud (không bị timeout vì Railway persistent)

Nếu CORS error trong DevTools console → kiểm tra `CORS_ORIGINS` ở Railway đúng URL Vercel chưa (KHÔNG có trailing slash, KHÔNG có `/api`).

---

## Bước 7 (tuỳ chọn) — Custom domain

**Vercel**: Settings → Domains → Add → trỏ DNS theo hướng dẫn.
**Railway**: Settings → Networking → Custom Domain → trỏ CNAME.

Sau khi có custom domain cho frontend, update lại `CORS_ORIGINS` ở Railway.

---

## Theo dõi chi phí Railway

- $5 credit/tháng đủ cho 1 service ~500-700 hrs (chạy 24/7 mất ~$5)
- App dùng pandas/vnstock có thể RAM peak 300-500MB → vẫn trong Hobby plan
- Tab **Usage** ở dashboard Railway xem real-time

Nếu vượt $5 credit:
- Service bị suspend tới đầu tháng sau (cycle reset 1st)
- Hoặc upgrade Pro $20/tháng

---

## Troubleshooting

### Backend build fail trên Railway
**Lỗi**: `Could not find a version that satisfies the requirement`
- Kiểm tra `backend/requirements.txt` đã pin đúng (vnstock>=4.0,<5.0)
- Vào Logs xem package nào fail — thường là vnstock dependency cũ. Thử pin `vnstock==4.0.4` cụ thể.

### vnstock fail với error region
- Logs có `Failed to fetch VN stock`: đổi Railway region về Singapore
- Settings → Region → `Asia Southeast (Singapore)` → redeploy

### Neon connection refused / too many connections
- Đảm bảo dùng **Pooled connection string** (có `-pooler` trong hostname)
- Reduce workers trong `railway.json`: `--workers 1`

### Frontend không gọi được backend
- DevTools Network: xem request có đúng URL Railway không
- Check `VITE_API_BASE` trong Vercel env (sau khi đổi cần redeploy)
- CORS error → bước 5

### Reset portfolio production
Vào Neon Console → SQL Editor:
```sql
DELETE FROM lot; DELETE FROM holding; DELETE FROM txn;
UPDATE portfolio SET cash = 100000000, created_at = EXTRACT(epoch FROM now()) * 1000;
```

### Cập nhật code
- `git push origin main` → cả Vercel và Railway tự deploy
- Railway có Preview deploys nếu bật trong Settings

---

## Local dev sau khi setup deploy

Local vẫn chạy bình thường:
- Không có `DATABASE_URL` → SQLite file `backend/data.db`
- Frontend gọi `http://127.0.0.1:8765/api` (default `VITE_API_BASE` undefined)

Để test production-like local:
```bash
# backend/.env
DATABASE_URL=postgresql://...neon.tech/...?sslmode=require
```

```bash
# frontend/.env.local
VITE_API_BASE=https://vn-stock-ai-backend-production-xxxx.up.railway.app
```
