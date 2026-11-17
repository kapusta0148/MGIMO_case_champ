import { Component, type ReactNode } from "react";

/** Последний рубеж: если экран упал при отрисовке, показываем понятное сообщение, а не пустую страницу. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    console.error("Ошибка интерфейса:", error);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main className="mx-auto grid min-h-dvh w-full max-w-md content-center gap-3 px-4 text-center">
        <h1 className="m-0 text-xl font-bold">Что-то пошло не так</h1>
        <p className="m-0 text-sm text-muted">
          Экран не удалось показать. Ваши данные в порядке — обновите страницу, чтобы продолжить.
        </p>
        <button
          onClick={() => window.location.reload()}
          className="mc-grad mx-auto min-h-11 rounded-xl px-5 text-sm font-bold"
        >
          Обновить страницу
        </button>
      </main>
    );
  }
}
