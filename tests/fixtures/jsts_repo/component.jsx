import React from 'react';

export function Button({ label, onClick }) {
  return (
    <button onClick={onClick} className="btn">
      {label}
    </button>
  );
}

export class Card extends React.Component {
  render() {
    return <div className="card">{this.props.children}</div>;
  }
}
