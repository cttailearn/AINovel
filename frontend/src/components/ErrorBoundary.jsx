import { Component } from 'react';

export class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('ErrorBoundary caught', error, info);
  }

  reset = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      return (
        <div className="error-boundary">
          <h2>出错了</h2>
          <p>{this.state.error.message || '页面发生未预期错误'}</p>
          <button type="button" className="btn btn-primary" onClick={this.reset}>
            重试
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
