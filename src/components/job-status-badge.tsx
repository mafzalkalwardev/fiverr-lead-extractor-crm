import { Badge } from "@/components/ui/badge";

const statusVariant: Record<string, "default" | "success" | "warning" | "danger" | "secondary"> = {
  pending: "secondary",
  running: "default",
  discovering_gigs: "default",
  extracting_reviews: "default",
  verification_required: "warning",
  paused: "secondary",
  retry_required: "warning",
  blocked: "danger",
  completed: "success",
  failed: "danger",
  stopped: "secondary",
};

const statusLabel: Record<string, string> = {
  discovering_gigs: "discovering gigs",
  extracting_reviews: "extracting reviews",
  verification_required: "verification required",
  retry_required: "retry required",
};

export function JobStatusBadge({ status }: { status: string }) {
  const label = statusLabel[status] || status.replace(/_/g, " ");
  return <Badge variant={statusVariant[status] || "secondary"}>{label}</Badge>;
}
