import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route } from 'react-router-dom';

import { TimerProvider } from "./components/TimerContext";
import { AppLayout } from './layouts/AppLayout';
import QuizRunPage from "./pages/QuizRunPage";
import { DeckListPage } from './pages/DeckListPage';
import { DeckPracticePage } from "./pages/DeckPracticePage.tsx";
import LoginPage from "./pages/LoginPage.tsx";
import { MainSelectPage } from "./pages/MainSelectPage.tsx";
import DeckEditPage from "./pages/DeckEditPage.tsx";
import CreateDeckPage from "./pages/CreateDeckPage.tsx";
import NewQuizTemplatePage from "./pages/NewQuizTemplatePage";
import QuizResultPage from "./pages/QuizResultPage";
import "katex/dist/katex.min.css";
import './index.css';
import NewDecksPage from "./pages/NewDecksPage";
import DueDecksPage from "./pages/DueDecksPage";
import MapPdfTestPage from "./pages/MapPdfTestPage.tsx";

ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
        <BrowserRouter>
            <Routes>
                <Route path="/login" element={<LoginPage />} />

                <Route element={<TimerProvider>
                        <AppLayout />
                    </TimerProvider>}>
                    <Route path="/" element={<MainSelectPage />} />
                    <Route path="/decks" element={<DeckListPage />} />
                    <Route path="/decks/:deckName/practice" element={<DeckPracticePage />} />
                    <Route path="/quizzes" element={<MainSelectPage />} />
                    <Route path="/quizzes/new" element={<NewQuizTemplatePage />} />
                    <Route path="/quizzes/:templateId/take" element={<QuizRunPage />} />
                    <Route path="/quiz-runs" element={<QuizResultPage />} />
                    <Route path="/quiz-runs/:quizId" element={<QuizResultPage />} />
                    <Route path="/quiz-runs/:quizId/:runId" element={<QuizResultPage />} />
                    <Route path="/decks/:deckId/edit" element={<DeckEditPage />} />
                    <Route path="/decks/new" element={<CreateDeckPage />} />
                    <Route path="/decks/newest" element={<NewDecksPage />} />
                    <Route path="/decks/due" element={<DueDecksPage />} />
                    <Route path="/debug/map-pdf" element={<MapPdfTestPage />} />
                </Route>
            </Routes>
        </BrowserRouter>
    </React.StrictMode>
);
