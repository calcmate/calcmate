import { useCallback, useEffect, useState } from 'react'
import { getBlogPosts } from '../api/client.js'

// /blog — 실제 운영 Blog(calcmate.kr) 전용 조회 화면(STEP 171).
// "articles" DB(Publish/Trash)와는 완전히 별개의 데이터 소스(blog_articles, WordPress 연동)를 읽는다.

export default function Blog() {
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    setFailed(false)
    getBlogPosts().then((res) => {
      setResult(res)
      setFailed(!res?.success)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const posts = result?.data?.posts || []

  return (
    <div className="page">
      <div className="page__header">
        <h1>Blog</h1>
        <button type="button" className="refresh-btn" onClick={load}>
          새로고침
        </button>
      </div>

      <p className="status-card__hint">
        현재 실제 공개 중인 calcmate.kr Blog 글 목록입니다(WordPress 연동 상태 기준). Article
        Publish/Trash와는 별개의 데이터입니다.
      </p>

      {loading && <p className="status-card__hint">불러오는 중...</p>}
      {!loading && failed && <p className="status-card__error">⚠ API 연결 실패</p>}

      {!loading && !failed && (
        <div className="status-card article-panel">
          <h3 className="status-card__title">Blog 글 ({result?.data?.total ?? 0}개)</h3>
          {posts.length ? (
            <table className="article-table">
              <thead>
                <tr>
                  <th>제목</th>
                  <th>slug</th>
                  <th>URL</th>
                </tr>
              </thead>
              <tbody>
                {posts.map((p) => (
                  <tr key={p.slug}>
                    <td>{p.title || '(제목없음)'}</td>
                    <td>{p.slug}</td>
                    <td>
                      {p.file_exists ? (
                        <a href={p.public_url} target="_blank" rel="noreferrer">
                          링크
                        </a>
                      ) : (
                        '-'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="status-card__hint">Blog 글이 없습니다.</p>
          )}
        </div>
      )}
    </div>
  )
}
