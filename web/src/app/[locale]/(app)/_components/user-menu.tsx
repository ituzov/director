import { getCurrentUser } from "@/lib/session";

import { UserDropdown } from "./user-dropdown";

/** Кто вошёл. Читает сессию, поэтому живёт только внутри Suspense. */
export async function UserMenu() {
  const user = await getCurrentUser();
  // в браузер только то, что нужно меню: не весь объект пользователя
  return <UserDropdown email={user.email} role={user.role} />;
}
