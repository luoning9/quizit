import { createContext, useContext, useEffect, useState } from "react";

interface TimerContextValue {
    seconds: number;
    running: boolean;
    start: () => void;
    pause: () => void;
    reset: () => void;
}

const TimerContext = createContext<TimerContextValue | null>(null);

export function TimerProvider({ children }: { children: React.ReactNode }) {
    const [seconds, setSeconds] = useState(0);
    const [running, setRunning] = useState(false);

    useEffect(() => {
        if (!running) return;

        const id = setInterval(() => {
            setSeconds((prev) => prev + 1);
        }, 1000);

        return () => clearInterval(id);
    }, [running]);

    return (
        <TimerContext.Provider
            value={{
                seconds,
                running,
                start: () => setRunning(true),
                pause: () => setRunning(false),
                reset: () => {
                    setSeconds(0);
                    setRunning(false);
                },
            }}
        >
            {children}
        </TimerContext.Provider>
    );
}

export function useTimer() {
    const ctx = useContext(TimerContext);
    if (!ctx) throw new Error("useTimer must be inside <TimerProvider>");
    return ctx;
}