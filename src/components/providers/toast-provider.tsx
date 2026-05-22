"use client";

import * as React from "react";
import {
  ToastProvider as RadixProvider,
  ToastViewport,
  Toast,
  ToastTitle,
  ToastDescription,
} from "@/components/ui/toast";

type ToastMessage = { title: string; description?: string };

const ToastContext = React.createContext<{
  toast: (msg: ToastMessage) => void;
}>({ toast: () => {} });

export function useToast() {
  return React.useContext(ToastContext);
}

export function AppToastProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = React.useState(false);
  const [message, setMessage] = React.useState<ToastMessage>({ title: "" });

  const toast = React.useCallback((msg: ToastMessage) => {
    setMessage(msg);
    setOpen(true);
  }, []);

  return (
    <ToastContext.Provider value={{ toast }}>
      <RadixProvider>
        {children}
        <Toast open={open} onOpenChange={setOpen} duration={4000}>
          <div className="grid gap-1">
            <ToastTitle>{message.title}</ToastTitle>
            {message.description && <ToastDescription>{message.description}</ToastDescription>}
          </div>
        </Toast>
        <ToastViewport />
      </RadixProvider>
    </ToastContext.Provider>
  );
}
