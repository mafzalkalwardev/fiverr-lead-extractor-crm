"use client";

import { useEffect, useState } from "react";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { User, Mail, Shield } from "lucide-react";
import { apiFetch } from "@/lib/api";

export default function UserProfilePage() {
  const [user, setUser] = useState<{ id?: string; name?: string; email?: string; role?: string; status?: string }>({});
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [statusType, setStatusType] = useState<"success" | "error" | "info">("info");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiFetch<{ user: { id: string; name: string; email: string; role: string; status: string } }>("/api/auth/me")
      .then((data) => {
        setUser(data.user);
        setName(data.user.name);
        setEmail(data.user.email);
      })
      .catch((error) => {
        setStatusType("error");
        setStatusMessage(error.message || "Failed to load profile.");
      });
  }, []);

  const saveProfile = async () => {
    setSaving(true);
    setStatusMessage(null);

    try {
      const payload = { name: name.trim(), email: email.trim().toLowerCase() };
      const data = await apiFetch<{ user: { id: string; name: string; email: string; role: string; status: string }; token: string }>(
        "/api/auth/me",
        {
          method: "PATCH",
          body: JSON.stringify(payload),
        }
      );

      setUser(data.user);
      setName(data.user.name);
      setEmail(data.user.email);
      setStatusType("success");
      setStatusMessage("Profile updated successfully.");
      localStorage.setItem("user", JSON.stringify(data.user));
      localStorage.setItem("token", data.token);
    } catch (error: unknown) {
      setStatusType("error");
      setStatusMessage(
        error instanceof Error ? error.message : "Unable to update profile."
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div>
          <h1 className="page-title">Profile Settings</h1>
          <p className="page-subtitle">Manage your account information and preferences.</p>
        </div>

        <Card className="max-w-2xl">
          <CardHeader>
            <CardTitle>Personal Information</CardTitle>
            <CardDescription>Update your personal details here.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {statusMessage ? (
              <div
                className={`rounded-md px-4 py-3 text-sm ${
                  statusType === "success"
                    ? "bg-emerald-500/10 text-emerald-300"
                    : statusType === "error"
                    ? "bg-red-500/10 text-red-300"
                    : "bg-slate-500/10 text-slate-300"
                }`}
              >
                {statusMessage}
              </div>
            ) : null}

            <div className="space-y-2">
              <Label htmlFor="profile-name">Full Name</Label>
              <div className="relative">
                <User className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                <Input
                  id="profile-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  className="pl-9"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="profile-email">Email Address</Label>
              <div className="relative">
                <Mail className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                <Input
                  id="profile-email"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  className="pl-9"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label>Account Role</Label>
              <div className="relative">
                <Shield className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                <Input
                  value={user.role === "admin" ? "Administrator" : "Standard User"}
                  readOnly
                  className="pl-9 bg-muted/50 capitalize"
                />
              </div>
            </div>

            <div className="pt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-sm text-muted-foreground">
                Use this form to update your name or email for your FT Solutions account.
              </div>
              <Button onClick={saveProfile} disabled={saving || !name || !email}>
                {saving ? "Saving..." : "Save Changes"}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </DashboardLayout>
  );
}
