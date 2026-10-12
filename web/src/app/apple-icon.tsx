import { logoImage } from "@/components/logo-image";

export const size = { width: 180, height: 180 };
export const contentType = "image/png";

/** Иконка на экран «Домой»: квадрат без скругления, углы iOS скругляет сама. */
export default function AppleIcon() {
  return logoImage(size.width, 0);
}
