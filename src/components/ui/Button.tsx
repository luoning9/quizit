import type { ButtonHTMLAttributes, ReactNode } from "react";
import clsx from "clsx";

type Variant = "primary" | "secondary" | "ghost" | "outline" | "link" | "none";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
    children: ReactNode;
    variant?: Variant;
    className?: string;
}

/**
 * 通用按钮（支持 light/dark 主题）
 */
export function Button({
                           children,
                           variant = "primary",
                           className = "",
                           disabled,
                           ...rest
                       }: ButtonProps) {
    const base =
        "inline-flex items-center justify-center rounded-xl font-medium transition-colors px-4 py-2 disabled:opacity-50 disabled:pointer-events-none";

    const variants: Record<Variant, string> = {
        none:"",
        primary:
            [
                // 浅色：低饱和深灰蓝，柔和阴影
                "bg-slate-900 text-slate-50 border border-slate-800/90",
                "hover:bg-slate-800 hover:border-slate-700",
                "active:bg-slate-900",
                "shadow-[0_8px_24px_-12px_rgba(15,23,42,0.45)]",

                // 深色：与背景融合的中灰蓝
                "dark:bg-slate-700 dark:text-slate-50",
                "dark:border-slate-600/80",
                "dark:hover:bg-slate-600 dark:hover:border-slate-500",
                "dark:active:bg-slate-700",
            ].join(" "),
        secondary:
        // 浅色
            "bg-slate-100 text-slate-800 hover:bg-slate-200 " +
            // 深色
            "dark:bg-slate-700 dark:text-slate-100 dark:hover:bg-slate-600",
        link:
        // 浅色模式
            "bg-transparent text-blue-600 hover:underline hover:text-blue-700 " +
            // 深色模式
            "dark:text-blue-400 dark:hover:text-blue-300 dark:hover:underline",
        outline:
        // 浅色模式
            "bg-transparent text-slate-700 border border-slate-400 hover:bg-slate-100 hover:border-slate-500 " +
            // 深色模式
            "dark:bg-transparent dark:text-slate-200 dark:border-slate-500 dark:hover:bg-slate-700/40 dark:hover:border-slate-300",
        ghost:
        // 浅色
            "bg-transparent text-slate-700 hover:bg-slate-100 " +
            // 深色
            "dark:text-slate-200 dark:hover:bg-slate-700",
    };

    return (
        <button
            disabled={disabled}
            className={clsx(base, variants[variant], className)}
            {...rest}
        >
            {children}
        </button>
    );
}
