import { Skeleton } from "@/components/ui/skeleton";
import type { AiConnection } from "@/lib/ai";

import { ConnectionCard } from "./connection-card";

export function ConnectionList({
  connections,
  empty,
}: {
  connections: AiConnection[];
  empty: string;
}) {
  if (connections.length === 0) {
    return <p className="text-sm text-muted-foreground">{empty}</p>;
  }
  return (
    <ul className="grid gap-4 md:grid-cols-2">
      {connections.map((connection) => (
        <li key={connection.id}>
          <ConnectionCard connection={connection} />
        </li>
      ))}
    </ul>
  );
}

export function ConnectionListSkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Skeleton className="h-40 rounded-xl" />
    </div>
  );
}
