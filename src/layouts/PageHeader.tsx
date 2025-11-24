import type { ReactNode } from "react";

interface PageHeaderProps {
    title: string;
    subtitle?: string;
    action?: ReactNode; // 右侧操作按钮
}

export function PageHeader({ title, subtitle, action }: PageHeaderProps) {
    return (
        <div className="mb-6 flex items-start justify-between">
            <div>
                <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
                {subtitle && (
                    <p className="mt-1 text-sm text-slate-500">{subtitle}</p>
                )}
            </div>

            {action && <div className="ml-4">{action}</div>}
        </div>
    );
}