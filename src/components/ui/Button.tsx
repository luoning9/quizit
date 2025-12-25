import React, { type ButtonHTMLAttributes, type ReactNode } from "react";
import clsx from "clsx";

type Variant =
    | "primary"
    | "secondary"
    | "ghost"
    | "ghostSecond"
    | "iconLearn"
    | "iconView"
    | "iconStart"
    | "iconGhost"
    | "outline"
    | "link"
    | "none";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
    children: ReactNode;
    variant?: Variant;
    className?: string;
}

/**
 * 通用按钮（支持 light/dark 主题）
 */
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
    {
        children,
        variant = "primary",
        className = "",
        disabled,
        ...rest
    }: ButtonProps,
    ref
) {
    const isIconVariant = variant.startsWith("icon");
    const base = isIconVariant
        ? "inline-flex items-center justify-center rounded-full transition-colors disabled:opacity-50 disabled:pointer-events-none"
        : "inline-flex items-center justify-center rounded-xl font-medium transition-colors px-4 py-2 disabled:opacity-50 disabled:pointer-events-none";

    const variants: Record<Variant, string> = {
        none:"",
        primary:
            [
                // 浅色：柔和绿色主按钮，更贴合整体浅色调
                "bg-emerald-600 text-white border border-emerald-700",
                "hover:bg-emerald-500 hover:border-emerald-600",
                "active:bg-emerald-700",
                "shadow-[0_8px_24px_-12px_rgba(16,185,129,0.45)]",

                // 深色：保持中性深灰蓝
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
            "bg-transparent text-blue-600 hover:underline hover:text-blue-900 hover:bg-blue-100 " +
            // 深色模式
            "dark:text-blue-300 dark:hover:text-white dark:hover:underline dark:hover:bg-slate-700",
        outline:
        // 浅色模式：更高对比度与浅阴影
            "bg-white text-slate-800 border border-slate-300 hover:bg-slate-200 hover:border-slate-500 hover:shadow-md shadow-sm " +
            // 深色模式保持不变
            "dark:bg-transparent dark:text-slate-200 dark:border-slate-500 dark:hover:bg-slate-700/40 dark:hover:border-slate-300",
        ghost:
        // 浅色
            "bg-transparent text-slate-700 hover:bg-slate-300 hover:text-slate-900 " +
            // 深色
            "dark:text-slate-200 dark:hover:bg-slate-600 dark:hover:text-white",
        ghostSecond:
            [
                // 浅色：低调、与 outline 区分的柔和色
                "bg-transparent text-teal-500 hover:bg-teal-50 hover:text-teal-600",
                // 深色
                "dark:text-teal-500 dark:hover:bg-teal-900/50 dark:hover:text-teal-200",
            ].join(" "),
        iconLearn:
            [
                "p-2 rounded-full",
                "bg-transparent text-emerald-600 hover:text-white hover:bg-emerald-600",
                "dark:text-emerald-300 dark:hover:text-emerald-50 dark:hover:bg-emerald-700",
            ].join(" "),
        iconView:
            [
                "p-2 rounded-full",
                "bg-transparent text-slate-600 hover:text-white hover:bg-slate-600",
                "dark:text-slate-300 dark:hover:text-slate-50 dark:hover:bg-slate-600",
            ].join(" "),
        iconStart:
            [
                "p-2 rounded-full",
                "bg-transparent text-blue-600 hover:text-white hover:bg-blue-600",
                "dark:text-blue-300 dark:hover:text-blue-50 dark:hover:bg-blue-700",
            ].join(" "),
        iconGhost:
            [
                "p-3 rounded-full",
                "bg-transparent text-slate-600 hover:text-white hover:bg-slate-600",
                "dark:text-slate-300 dark:hover:text-slate-100 dark:hover:bg-slate-700",
            ].join(" "),
    };

    return (
        <button
            ref={ref}
            disabled={disabled}
            className={clsx(base, variants[variant], className)}
            {...rest}
        >
            {children}
        </button>
    );
});
