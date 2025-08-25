"use client";
import { useState } from "react";
import UserProfile from "@/components/auth/UserProfile";

export default function Page() {
    const [user] = useState({ email: "admin@example.com", roles: ["admin"], subscription_id: "12345678-1234-1234-1234-123456789012" });
    return <UserProfile user={user} onLogout={() => { location.href = "/login"; }} />;
}
