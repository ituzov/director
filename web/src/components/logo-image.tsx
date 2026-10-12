import { ImageResponse } from "next/og";

import { LOGO_PATH, LOGO_TRANSFORM, LOGO_VIEWBOX } from "./logo";

// цвет --brand из globals.css: картинка рисуется без CSS, переменные ей не видны
const BRAND = "#1f2597";

/** Знак PNG-картинкой для иконок: белая «Д» на фирменном синем. */
export function logoImage(size: number, radius: number) {
  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        background: BRAND,
        borderRadius: radius,
      }}
    >
      <svg viewBox={LOGO_VIEWBOX} width={size} height={size}>
        <path transform={LOGO_TRANSFORM} fill="#ffffff" d={LOGO_PATH} />
      </svg>
    </div>,
    { width: size, height: size },
  );
}
