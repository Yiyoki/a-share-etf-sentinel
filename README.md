# A股国家队 ETF 三因子前端

Cloudflare Pages 静态前端。后端 API 由 default VPS 提供。

## API

默认 API Base：

```text
https://api-a-share-etf.yiyoki.com/a-share-etf/api/
```

如需临时改 API，可在页面加载前设置：

```html
<script>window.A_SHARE_ETF_API_BASE = "https://example.com/a-share-etf/api/";</script>
```

## 部署

Cloudflare Pages no-build：

- Build command：空
- Output directory：`.`

## 访问地址

- 自定义域名：https://kikistock.980822.xyz/
- Pages 域名：https://a-share-etf-sentinel.pages.dev/
