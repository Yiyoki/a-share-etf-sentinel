const ORIGIN_API = 'http://39.107.137.91/a-share-etf/api';

const EASTMONEY_HEADERS = {
  'Accept': 'application/json,text/plain,*/*',
  'Accept-Language': 'zh-CN,zh;q=0.9',
  'Referer': 'https://quote.eastmoney.com/center/boardlist.html',
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36',
};

const INDEX_SECIDS = ['1.000001', '0.399001', '0.399006', '1.000688', '1.000300', '1.000016', '0.399905', '0.399852'];

const direction = pct => pct > 0.2 ? 'up' : (pct < -0.2 ? 'down' : 'flat');
const asNum = v => Number.isFinite(Number(v)) ? Number(v) : 0;
const nodeFromEastMoney = (raw, type, divisor) => {
  const pct = asNum(raw.f3);
  const amount = asNum(raw.f6);
  return {
    code: raw.f12 || '',
    name: raw.f14 || '--',
    type,
    pct_chg: pct,
    latest: asNum(raw.f2),
    amount,
    direction: direction(pct),
    visual_size: Math.max(1, amount / divisor),
  };
};

async function fetchJson(url, retries = 2) {
  let lastError;
  for (let i = 0; i <= retries; i++) {
    try {
      const res = await fetch(url, { headers: EASTMONEY_HEADERS, cf: { cacheTtl: 0, cacheEverything: false } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      lastError = err;
    }
  }
  throw lastError;
}

async function marketCloudResponse() {
  const idxUrl = new URL('https://push2.eastmoney.com/api/qt/ulist.np/get');
  idxUrl.search = new URLSearchParams({
    fltt: '2', invt: '2', fields: 'f12,f14,f2,f3,f5,f6,f20', secids: INDEX_SECIDS.join(','), _: String(Date.now()),
  });
  const boardParams = (fs) => new URLSearchParams({
    pn: '1', pz: '36', po: '1', np: '1', fltt: '2', invt: '2', fid: 'f6', fs, fields: 'f12,f14,f2,f3,f5,f6,f20', _: String(Date.now()),
  });
  const industryUrl = new URL('https://push2.eastmoney.com/api/qt/clist/get');
  industryUrl.search = boardParams('m:90+t:2');
  const conceptUrl = new URL('https://push2.eastmoney.com/api/qt/clist/get');
  conceptUrl.search = boardParams('m:90+t:3');

  const [idx, industry, concept] = await Promise.all([fetchJson(idxUrl), fetchJson(industryUrl), fetchJson(conceptUrl)]);
  const idxRows = idx?.data?.diff || [];
  const wanted = Object.fromEntries(INDEX_SECIDS.map((x, i) => [x.split('.')[1], i]));
  const indices = idxRows.map(x => nodeFromEastMoney(x, 'index', 100000000000)).sort((a, b) => (wanted[a.code] ?? 999) - (wanted[b.code] ?? 999));
  const payload = {
    trade_date: new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 10),
    source: 'eastmoney.realtime.pages-function',
    indices,
    industry: (industry?.data?.diff || []).map(x => nodeFromEastMoney(x, 'industry', 1000000000)),
    concept: (concept?.data?.diff || []).map(x => nodeFromEastMoney(x, 'concept', 1000000000)),
  };
  return new Response(JSON.stringify(payload), {
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Access-Control-Allow-Origin': '*',
      'Cache-Control': 'no-store',
    },
  });
}

export async function onRequest(context) {
  const url = new URL(context.request.url);
  const path = Array.isArray(context.params.path) ? context.params.path.join('/') : (context.params.path || '');
  if (context.request.method === 'GET' && path === 'market-cloud') {
    try {
      return await marketCloudResponse();
    } catch (err) {
      const fallback = await fetch(new URL('/data/market-cloud.json', url.origin), { cf: { cacheTtl: 0, cacheEverything: false } });
      const headers = new Headers(fallback.headers);
      headers.set('Access-Control-Allow-Origin', '*');
      headers.set('Cache-Control', 'no-store');
      headers.set('X-Market-Cloud-Fallback', 'static-json');
      return new Response(fallback.body, { status: fallback.status, statusText: fallback.statusText, headers });
    }
  }
  const upstream = `${ORIGIN_API}/${path}${url.search}`;
  const response = await fetch(upstream, {
    method: context.request.method,
    headers: {
      'Accept': context.request.headers.get('Accept') || 'application/json',
      'User-Agent': 'Mozilla/5.0 (compatible; AShareETFSentinelPagesProxy/1.0)',
    },
    body: ['GET', 'HEAD'].includes(context.request.method) ? undefined : context.request.body,
  });
  const headers = new Headers(response.headers);
  headers.set('Access-Control-Allow-Origin', '*');
  headers.set('Cache-Control', context.request.method === 'GET' ? 'public, max-age=60' : 'no-store');
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}

export const onRequestGet = onRequest;
export const onRequestHead = onRequest;
export const onRequestPost = onRequest;
export function onRequestOptions() {
  return new Response(null, {
    status: 204,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, HEAD, POST, OPTIONS',
      'Access-Control-Allow-Headers': '*',
      'Access-Control-Max-Age': '86400',
    },
  });
}
