import { createNavigation } from "next-intl/navigation";

import { routing } from "./routing";

// обёртки над навигацией Next, которые знают про локаль
export const { Link, redirect, usePathname, useRouter, getPathname } = createNavigation(routing);
