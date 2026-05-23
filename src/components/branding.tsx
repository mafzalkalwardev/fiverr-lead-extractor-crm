import { COMPANY_NAME, COMPANY_PHONE, APP_NAME } from "@/lib/constants";

export function BrandLogo({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-start gap-2">
      <img src="/ftsolutionslogo.jpg" alt="" width={32} height={32} className="rounded-lg shrink-0 object-contain" />
      <div>
      <p className="text-lg font-bold text-primary leading-tight">
        {compact ? "Lead CRM" : APP_NAME}
      </p>
      {!compact && (
        <p className="text-xs text-muted-foreground mt-0.5">
          {COMPANY_NAME} · {COMPANY_PHONE}
        </p>
      )}
      </div>
    </div>
  );
}

export function BrandFooter() {
  return (
    <p className="text-center text-xs text-muted-foreground">
      {COMPANY_NAME} · {COMPANY_PHONE}
    </p>
  );
}
