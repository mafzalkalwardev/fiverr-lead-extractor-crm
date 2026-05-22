"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import { useToast } from "@/components/providers/toast-provider";
import { BrandLogo, BrandFooter } from "@/components/branding";
import { APP_NAME } from "@/lib/constants";
import { Shield } from "lucide-react";

export default function LoginPage() {
  const router = useRouter();
  const { toast } = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const data = await apiFetch<{ token: string; user: object }>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      localStorage.setItem("token", data.token);
      localStorage.setItem("user", JSON.stringify(data.user));
      toast({ title: "Welcome back", description: "Signed in successfully." });
      const user = data.user as { role?: string };
      router.push(user.role === "admin" ? "/admin" : "/dashboard");
    } catch (err) {
      toast({
        title: "Sign in failed",
        description: err instanceof Error ? err.message : "Check your email and password.",
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-background p-6">
      <div
        className="pointer-events-none absolute inset-0 opacity-40"
        aria-hidden
        style={{
          background:
            "radial-gradient(ellipse 80% 50% at 50% -20%, hsl(142 76% 45% / 0.15), transparent), radial-gradient(ellipse 60% 40% at 100% 100%, hsl(217 33% 25% / 0.4), transparent)",
        }}
      />
      <Card className="relative w-full max-w-md border-border/80 bg-card/95 shadow-2xl backdrop-blur-sm">
        <CardHeader className="space-y-6 pb-2 text-center">
          <div className="flex justify-center">
            <BrandLogo />
          </div>
          <div className="space-y-1">
            <CardDescription className="text-base text-muted-foreground">
              Sign in to {APP_NAME}
            </CardDescription>
            <p className="text-xs text-muted-foreground/80">
              US &amp; Canada lead extraction · secure workspace
            </p>
          </div>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="space-y-2">
              <Label htmlFor="email">Work email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                className="h-11"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="h-11"
                required
              />
            </div>
            <Button type="submit" className="h-11 w-full text-base" disabled={loading}>
              {loading ? "Signing in…" : "Sign in"}
            </Button>
          </form>
          <p className="mt-6 flex items-center justify-center gap-1.5 text-xs text-muted-foreground">
            <Shield className="h-3.5 w-3.5 shrink-0 opacity-70" />
            Credentials are issued by your administrator only.
          </p>
        </CardContent>
      </Card>
      <div className="relative mt-8">
        <BrandFooter />
      </div>
    </div>
  );
}
