import { useState } from "react";
import { Button } from "../../../../components/ui/Button";
import { Card } from "../../../../components/ui/Card";
import { useReconnectBlinkit } from "../../hooks";

export const ReconnectBlinkit = () => {
    const [open, setOpen] = useState(false);
    const [magicLink, setMagicLink] = useState("");
    const { mutate, isPending, isSuccess, isError, error, reset } = useReconnectBlinkit();

    const handleSubmit = () => {
        if (!magicLink.trim()) return;
        mutate(magicLink.trim(), {
            onSuccess: () => {
                setMagicLink("");
                setOpen(false);
            },
        });
    };

    return (
        <Card title="Blinkit Connection">
            {!open ? (
                <div className="flex items-center justify-between">
                    <p className="text-sm text-content-muted">
                        Session expired? Paste the magic link from your Blinkit email to reconnect.
                    </p>
                    <Button size="sm" variant="secondary" onClick={() => { reset(); setOpen(true); }}>
                        Reconnect
                    </Button>
                </div>
            ) : (
                <div className="flex flex-col gap-3">
                    <div className="rounded-md bg-muted px-3 py-2 text-xs text-content-muted">
                        <p className="font-medium text-content">How to get the magic link:</p>
                        <ol className="mt-1 list-decimal pl-4 space-y-0.5">
                            <li>Go to <span className="font-mono">brands.blinkit.com</span></li>
                            <li>Click <strong>Log In</strong>, enter your email</li>
                            <li>Check your email — click the link to copy its URL</li>
                            <li>Paste the full URL below</li>
                        </ol>
                    </div>

                    <textarea
                        value={magicLink}
                        onChange={(e) => setMagicLink(e.target.value)}
                        placeholder="https://brands.blinkit.com/__/auth/action?oobCode=..."
                        rows={3}
                        className="w-full rounded-md border border-border bg-card px-3 py-2 text-xs text-content outline-none focus:border-primary resize-none font-mono"
                    />

                    {isError && (
                        <p className="text-xs text-danger">
                            {error?.response?.data?.detail ?? "Reconnect failed. Check the link and try again."}
                        </p>
                    )}
                    {isSuccess && (
                        <p className="text-xs text-success">Session reconnected successfully.</p>
                    )}

                    <div className="flex gap-2">
                        <Button onClick={handleSubmit} disabled={isPending || !magicLink.trim()}>
                            {isPending ? "Connecting…" : "Connect"}
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => { setOpen(false); reset(); }}>
                            Cancel
                        </Button>
                    </div>
                </div>
            )}
        </Card>
    );
};

