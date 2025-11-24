// src/App.tsx
import { useEffect, useState } from 'react';
import { supabase } from '../lib/supabaseClient';

interface Deck {
    id: string;
    title: string;
}

function App() {
    const [decks, setDecks] = useState<Deck[]>([]);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        async function loadDecks() {
            const { data, error } = await supabase
                .from('decks')
                .select('id,title')
                .limit(5);

            if (error) {
                console.error(error);
                setError(error.message);
            } else if (data) {
                setDecks(data as Deck[]);
            }
        }

        loadDecks();
    }, []);

    return (
        <div style={{ padding: 24 }}>
            <h1>Supabase 测试</h1>
            {error && <div>出错了：{error}</div>}
            {!error && decks.length === 0 && <div>没有读取到任何 deck。</div>}
            <ul>
                {decks.map((d) => (
                    <li key={d.id}>{d.title}</li>
                ))}
            </ul>
        </div>
    );
}

export default App;