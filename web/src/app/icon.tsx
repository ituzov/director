import { logoImage } from "@/components/logo-image";

export const size = { width: 64, height: 64 };
export const contentType = "image/png";

/** Иконка вкладки: знак со скруглением, как в шапке входа. */
export default function Icon() {
  return logoImage(size.width, 14);
}
