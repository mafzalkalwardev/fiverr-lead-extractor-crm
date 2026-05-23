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

export default function RegisterPage() {
  const router = useRouter();
  const { toast } = useToast();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const data = await apiFetch<{ token: string; user: object }>("/api/auth/register", {
        method: "POST",
        body: JSON.stringify({ name, email, password }),
      });
      localStorage.setItem("token", data.token);
      localStorage.setItem("user", JSON.stringify(data.user));
      toast({ title: "Welcome", description: "Account created successfully." });
      const user = data.user as { role?: string };
      router.replace(user.role === "admin" ? "/admin" : "/dashboard");
    } catch (err) {
      toast({
        title: "Registration failed",
        description: err instanceof Error ? err.message : "Could not create account.",
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div suppressHydrationWarning className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-background p-6">
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
              Create an account for {APP_NAME}
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="space-y-2">
              <Label htmlFor="name">Full Name</Label>
              <Input
                id="name"
                type="text"
                autoComplete="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="John Doe"
                className="h-11"
                required
              />
            </div>
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
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="h-11"
                required
              />
            </div>
            <Button type="submit" className="h-11 w-full text-base" disabled={loading}>
              {loading ? "Creating account…" : "Create account"}
            </Button>
          </form>
          <div className="mt-6 text-center text-sm">
            <span className="text-muted-foreground">Already have an account? </span>
            <a href="/login" className="font-medium text-primary hover:underline">
              Sign in
            </a>
          </div>
        </CardContent>
      </Card>
      <div className="relative mt-8">
        <BrandFooter />
      </div>
    </div>
  );
}
