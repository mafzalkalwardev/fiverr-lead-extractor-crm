"use client";

import { useEffect, useState } from "react";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import { useToast } from "@/components/providers/toast-provider";
import type { User } from "@/types";

export default function AdminUsersPage() {
  const { toast } = useToast();
  const [users, setUsers] = useState<User[]>([]);
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "user" });

  const load = () =>
    apiFetch<{ users: User[] }>("/api/admin/users")
      .then((d) => setUsers(d.users))
      .catch((e) => toast({ title: "Error", description: String(e) }));

  useEffect(() => {
    load();
  }, []);

  const createUser = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await apiFetch("/api/admin/users", {
        method: "POST",
        body: JSON.stringify(form),
      });
      toast({ title: "User created" });
      setForm({ name: "", email: "", password: "", role: "user" });
      load();
    } catch (err) {
      toast({ title: "Failed", description: err instanceof Error ? err.message : "" });
    }
  };

  const toggleStatus = async (id: string, status: "active" | "inactive") => {
    await apiFetch(`/api/admin/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    });
    load();
  };

  const resetPassword = async (id: string) => {
    const password = prompt("New password (min 6 chars):");
    if (!password) return;
    await apiFetch(`/api/admin/users/${id}`, {
      method: "POST",
      body: JSON.stringify({ password }),
    });
    toast({ title: "Password reset" });
  };

  return (
    <DashboardLayout>
      <h1 className="text-3xl font-bold mb-8">Users</h1>

      <Card className="mb-8 max-w-md">
        <CardHeader>
          <CardTitle>Create User</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={createUser} className="space-y-3">
            <div>
              <Label>Name</Label>
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            </div>
            <div>
              <Label>Email</Label>
              <Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
            </div>
            <div>
              <Label>Password</Label>
              <Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
            </div>
            <div>
              <Label>Role</Label>
              <select
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={form.role}
                onChange={(e) => setForm({ ...form, role: e.target.value })}
              >
                <option value="user">User</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            <Button type="submit" className="w-full">Create</Button>
          </form>
        </CardContent>
      </Card>

      <div className="rounded-lg border border-border overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/50">
              <th className="p-3 text-left">Name</th>
              <th className="p-3 text-left">Email</th>
              <th className="p-3 text-left">Role</th>
              <th className="p-3 text-left">Status</th>
              <th className="p-3 text-left">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u._id} className="border-b border-border/50">
                <td className="p-3">{u.name}</td>
                <td className="p-3">{u.email}</td>
                <td className="p-3">{u.role}</td>
                <td className="p-3">{u.status}</td>
                <td className="p-3 flex flex-wrap gap-2">
                  {u.status === "active" ? (
                    <Button size="sm" variant="outline" onClick={() => toggleStatus(u._id, "inactive")}>
                      Deactivate
                    </Button>
                  ) : (
                    <Button size="sm" variant="outline" onClick={() => toggleStatus(u._id, "active")}>
                      Activate
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" onClick={() => resetPassword(u._id)}>
                    Reset PW
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </DashboardLayout>
  );
}
