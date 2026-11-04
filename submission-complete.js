// 접수 성공을 확인한 뒤에만 호출하는 공통 완료창입니다.
window.showSubmissionComplete = function({title, message, onConfirm}) {
  const previous = document.activeElement;
  const previousOverflow = document.body.style.overflow;
  const dialog = document.createElement('dialog');
  dialog.className = 'submission-complete';
  dialog.setAttribute('aria-labelledby', 'submissionCompleteTitle');
  dialog.setAttribute('aria-describedby', 'submissionCompleteMessage');
  const heading = document.createElement('h2');
  heading.id = 'submissionCompleteTitle';
  heading.textContent = title;
  const description = document.createElement('p');
  description.id = 'submissionCompleteMessage';
  description.textContent = message;
  const confirm = document.createElement('button');
  confirm.type = 'button';
  confirm.className = 'btn';
  confirm.textContent = '확인';
  dialog.append(heading, description, confirm);
  dialog.addEventListener('cancel', event => event.preventDefault());
  dialog.addEventListener('keydown', event => {
    if (event.key === 'Tab') { event.preventDefault(); confirm.focus(); }
  });
  confirm.addEventListener('click', () => {
    dialog.close();
    dialog.remove();
    document.body.style.overflow = previousOverflow;
    if (previous?.isConnected) previous.focus();
    onConfirm?.();
  }, {once: true});
  document.body.append(dialog);
  document.body.style.overflow = 'hidden';
  dialog.showModal();
  confirm.focus();
};
