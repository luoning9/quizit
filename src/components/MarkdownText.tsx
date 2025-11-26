import type { ComponentProps } from "react";
import clsx from "clsx";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import type { Components } from "react-markdown";

type MarkdownTextProps = {
    content: string;
    inline?: boolean;
    className?: string;
};

/**
 * 统一的 Markdown + LaTeX 渲染器，支持 GFM 和 KaTeX。
 * inline=true 时用于行内选项等场景，减少段落间距。
 */
export function MarkdownText({ content, inline = false, className }: MarkdownTextProps) {
    if (!content) return null;

    const baseComponents: Components = {
        a: ({ className, ...rest }: ComponentProps<"a">) => (
            <a
                {...rest}
                target="_blank"
                rel="noreferrer"
                className={clsx("underline decoration-slate-300", className)}
            />
        ),
    };

    const components: Components = inline
        ? {
            ...baseComponents,
            p: ({ children, className, ...rest }: ComponentProps<"p">) => (
                <span
                    {...rest}
                    className={clsx("whitespace-pre-wrap", className)}
                >
                    {children}
                </span>
            ),
        }
        : {
            ...baseComponents,
            p: ({ children, className, ...rest }: ComponentProps<"p">) => (
                <p
                    {...rest}
                    className={clsx("whitespace-pre-wrap", className)}
                >
                    {children}
                </p>
            ),
        };

    return (
        <div
            className={clsx(
                inline
                    ? "inline-block leading-snug whitespace-pre-wrap text-inherit"
                    : "space-y-2 leading-relaxed whitespace-pre-wrap text-inherit",
                "markdown-text",
                className,
            )}
        >
            <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkMath]}
                rehypePlugins={[rehypeKatex]}
                components={components}
            >
                {content}
            </ReactMarkdown>
        </div>
    );
}

export default MarkdownText;
