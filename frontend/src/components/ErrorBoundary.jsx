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
      // 修复 #27: 支持 scope 标签与默认降级文案, 让每个一级页面可以独立
      // 出错降级, 不再让 Workbench 抛错导致 Creation Studio 也白屏.
      const { scope = '页面', fallbackTitle = '出错了' } = this.props || {};
      return (
        <div className="error-boundary">
          <h2>{fallbackTitle}</h2>
          <p>{this.state.error.message || `${scope}发生未预期错误`}</p>
          <button type="button" className="btn btn-primary" onClick={this.reset}>
            重试
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
