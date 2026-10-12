// Нагрузка «залетел рилс»: шквал комментов с кодовым словом приходит вебхуками Meta.
// K6_WEB_DASHBOARD=true k6 run -e TARGET=https://1-2-3-4.sslip.io loadtest/webhooks.js
// Графики вживую: http://localhost:5665
import crypto from "k6/crypto";
import http from "k6/http";
import { check } from "k6";

const TARGET = __ENV.TARGET;
// тот же секрет и аккаунт, что кладёт seed.py
const SECRET = __ENV.SECRET || "loadtest-secret";
const ACCOUNT = "17841499999999999";
// пять постов: общий автоответ слышит любой
const POSTS = [
  "18100000000000001",
  "18100000000000002",
  "18100000000000003",
  "18100000000000004",
  "18100000000000005",
];
const PEAK = Number(__ENV.PEAK || 200);

export const options = {
  discardResponseBodies: true,
  scenarios: {
    // вебхуки: шлём с заданной частотой, независимо от того, как быстро отвечает сервер
    reel: {
      executor: "ramping-arrival-rate",
      exec: "comment",
      startRate: 5,
      timeUnit: "1s",
      preAllocatedVUs: 50,
      maxVUs: 500,
      stages: [
        { target: 10, duration: "30s" },
        { target: 50, duration: "1m" },
        { target: 100, duration: "1m" },
        { target: PEAK, duration: "1m" },
        { target: PEAK, duration: "1m" },
        { target: 0, duration: "30s" },
      ],
    },
    // владелец в это время открывает админку: не тормозит ли web
    admin: {
      executor: "constant-arrival-rate",
      exec: "admin",
      rate: 2,
      timeUnit: "1s",
      duration: "5m",
      preAllocatedVUs: 5,
    },
  },
  thresholds: {
    // Meta ждёт быстрый 200 и при таймаутах повторяет вебхук
    "http_req_duration{scenario:reel}": ["p(95)<1000"],
    "http_req_failed{scenario:reel}": ["rate<0.01"],
    "http_req_duration{scenario:admin}": ["p(95)<2000"],
  },
};

const digits = (n) =>
  Array.from({ length: n }, () => Math.floor(Math.random() * 10)).join("");

export function comment() {
  const body = JSON.stringify({
    object: "instagram",
    entry: [
      {
        id: ACCOUNT,
        time: Math.floor(Date.now() / 1000),
        changes: [
          {
            field: "comments",
            value: {
              // каждый коммент и человек свои: выдача одна на человека и пост
              id: `18${digits(15)}`,
              text: "хочу гайд",
              from: {
                id: `27${digits(15)}`,
                username: `user${__VU}_${__ITER}`,
              },
              media: { id: POSTS[__ITER % POSTS.length] },
            },
          },
        ],
      },
    ],
  });
  const signature = "sha256=" + crypto.hmac("sha256", SECRET, body, "hex");
  const res = http.post(`${TARGET}/webhooks/instagram`, body, {
    headers: {
      "Content-Type": "application/json",
      "X-Hub-Signature-256": signature,
    },
  });
  check(res, { "вебхук принят": (r) => r.status === 200 });
}

export function admin() {
  const res = http.get(`${TARGET}/login`);
  check(res, { "страница открылась": (r) => r.status === 200 });
}
