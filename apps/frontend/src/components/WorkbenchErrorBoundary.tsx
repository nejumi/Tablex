import React from "react";
import { RefreshCw } from "lucide-react";

export class WorkbenchErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { message: string | null }
> {
  state = { message: null };

  static getDerivedStateFromError(error: unknown) {
    return { message: error instanceof Error ? error.message : String(error) };
  }

  render() {
    if (this.state.message) {
      return (
        <div className="fatal-error">
          <img src="/mascot/tablee-empty.svg" alt="" aria-hidden="true" className="empty-state-mascot" />
          <h1>Tablex could not render this view.</h1>
          <p>{this.state.message}</p>
          <button className="primary-button" type="button" onClick={() => window.location.reload()}>
            <RefreshCw size={16} />
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
