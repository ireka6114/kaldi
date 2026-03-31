export KALDI_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")"/../../.. && pwd)
[ -f "$KALDI_ROOT/tools/env.sh" ] && . "$KALDI_ROOT/tools/env.sh"
export PATH="$PWD/utils:$KALDI_ROOT/tools/openfst/bin:$KALDI_ROOT/src/bin:$KALDI_ROOT/src/fstbin:$KALDI_ROOT/src/gmmbin:$KALDI_ROOT/src/featbin:$KALDI_ROOT/src/latbin:$KALDI_ROOT/src/lmbin:$KALDI_ROOT/src/nnet3bin:$KALDI_ROOT/src/online2bin:$PWD:$PATH"
[ ! -f "$KALDI_ROOT/tools/config/common_path.sh" ] && echo >&2 "Missing $KALDI_ROOT/tools/config/common_path.sh" && exit 1
. "$KALDI_ROOT/tools/config/common_path.sh"
export LC_ALL=C
export PYTHONUNBUFFERED=1
