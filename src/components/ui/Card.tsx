import type { HTMLAttributes, ReactNode } from "react";
import clsx from "clsx";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
    children: ReactNode;
    className?: string;
}

/**
 * 通用卡片组件（支持 light / dark）
 */
export function Card({ children, className = "", ...rest }: CardProps) {
    return (
        <div
            {...rest}
            className={clsx(
                // 基础白色主题
                "rounded-2xl shadow-soft p-4 bg-white",

                // 深色主题（Tailwind v4）
                "dark:bg-slate-800 dark:border-slate-700 dark:text-slate-100",

                // 外部传入的 className
                className
            )}
        >
            {children}
        </div>
    );
}