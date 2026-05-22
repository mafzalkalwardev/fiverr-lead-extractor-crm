import "@/lib/load-env";
import IORedis from "ioredis";

const REDIS_URL = process.env.REDIS_URL || "redis://127.0.0.1:6380";

/** Shared Redis connection for BullMQ. */
export function createRedisConnection(): IORedis {
  return new IORedis(REDIS_URL, {
    maxRetriesPerRequest: null,
    connectTimeout: 5000,
    retryStrategy: (times) => (times > 3 ? null : Math.min(times * 200, 2000)),
  });
}

export function isRedisConnectionError(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err);
  return (
    msg.includes("ECONNREFUSED") ||
    msg.includes("ENOTFOUND") ||
    msg.includes("ETIMEDOUT") ||
    msg.includes("Redis version needs to be greater or equal than 5")
  );
}
